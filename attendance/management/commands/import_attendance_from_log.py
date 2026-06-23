"""
Recover historical attendance by parsing punches out of zkteco_debug.log.

The biometric device pushed punches to the server in real time; every push was
written to the debug log. When device->employee mappings were missing (or wrong)
at push time, those punches were skipped and never became AttendanceRecords.
This command re-reads the log, applies the CURRENT mappings, and imports the
punches — recovering history the device may no longer hold in its own memory.

It uses the same grouping/upsert logic as the live ADMS sync:
  - device clock is PST (America/Los_Angeles); we convert to EST for storage
  - punches grouped per (employee, EST date); first = check-in, last = check-out
  - existing records tied to a leave request or public holiday are left untouched
  - device IDs in settings.ZK_IGNORED_DEVICE_IDS are dropped

Usage:
    python manage.py import_attendance_from_log --dry-run
    python manage.py import_attendance_from_log
    python manage.py import_attendance_from_log --from 2026-02-01 --to 2026-05-31
    python manage.py import_attendance_from_log --log /path/to/zkteco_debug.log
"""
import re
from collections import defaultdict
from datetime import datetime, date as date_cls
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from attendance.models import AttendanceRecord, DeviceEmployee
from attendance.services import compute_attendance_flags


# Matches a device punch line anywhere on a log line (handles a leading
# "BODY   : " prefix). Groups: BIO_ID, ATT_TIME, VERIFY, STATUS.
PUNCH_RE = re.compile(
    r"(\d{1,7})\s+(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+(\d+)\s+(-?\d+)"
)


class Command(BaseCommand):
    help = "Recover historical attendance by parsing punches out of zkteco_debug.log"

    def add_arguments(self, parser):
        parser.add_argument("--log", default="zkteco_debug.log", help="Path to the debug log")
        parser.add_argument("--from", dest="from_date", default=None,
                            help="Only import punches on/after this device (PST) date YYYY-MM-DD")
        parser.add_argument("--to", dest="to_date", default=None,
                            help="Only import punches on/before this device (PST) date YYYY-MM-DD")
        parser.add_argument("--dry-run", action="store_true",
                            help="Parse and report counts without writing any records")
        parser.add_argument("--device-tz", dest="device_tz", default=None,
                            help="Override the device clock timezone (e.g. 'UTC') used to "
                                 "interpret log timestamps. Needed to reconstruct history "
                                 "recorded before the device was switched to UTC-8 — it ran "
                                 "on UTC (TimeZone=0) until ~2026-06-15. "
                                 "Defaults to the Device Timezone setting.")
        parser.add_argument("--replace", action="store_true",
                            help="On update, overwrite check_out unconditionally (even to None) "
                                 "instead of only when a new value exists. Use when reconstructing "
                                 "a date range from a complete log slice so stale check-outs are "
                                 "cleared. Without it, an existing check_out is preserved.")
        parser.add_argument("--show-emp", dest="show_emp", type=int, default=None,
                            help="In --dry-run, print the computed check-in/out for this "
                                 "employee pk so the result can be validated before writing.")

    def handle(self, *args, **opts):
        log_path = opts["log"]
        dry = opts["dry_run"]
        try:
            d_from = date_cls.fromisoformat(opts["from_date"]) if opts["from_date"] else None
            d_to = date_cls.fromisoformat(opts["to_date"]) if opts["to_date"] else None
        except ValueError:
            raise CommandError("Dates must be YYYY-MM-DD")

        if dry:
            self.stdout.write(self.style.WARNING("DRY RUN — no records will be written\n"))

        from attendance.models import SystemSetting
        from attendance.tz_utils import device_workday, WORKDAY_BOUNDARY_HOUR
        device_tz_name = opts["device_tz"] or SystemSetting.get_device_timezone()
        try:
            _device_tz = ZoneInfo(device_tz_name)
        except Exception:
            raise CommandError(f"Unknown --device-tz '{device_tz_name}'")
        self.stdout.write(f"Interpreting device timestamps as: {device_tz_name}")
        replace = opts["replace"]
        show_emp = opts["show_emp"]
        # Use the afternoon-shift workday cutoff for normal (forward) imports. When
        # reconstructing an old era via --device-tz, the cutoff is calibrated for the
        # current PKT shifts and would mis-bucket, so disable it (boundary 0).
        _boundary = 0 if opts["device_tz"] else WORKDAY_BOUNDARY_HOUR

        ignored = {int(x) for x in getattr(settings, "ZK_IGNORED_DEVICE_IDS", [])}
        mappings = {dm.device_user_id: dm.employee
                    for dm in DeviceEmployee.objects.select_related("employee")}

        seen = set()                 # (device_uid, att_time_str) — dedup massive log repetition
        unknown = set()
        punches = defaultdict(list)  # (emp_pk, local_date) -> [(time, status_code)]
        unique = 0

        try:
            fh = open(log_path, "r", encoding="utf-8", errors="replace")
        except OSError as exc:
            raise CommandError(f"Cannot open log: {exc}")

        with fh:
            for line in fh:
                m = PUNCH_RE.search(line)
                if not m:
                    continue
                device_uid = int(m.group(1))
                att_time_str = m.group(2)
                try:
                    status_code = int(m.group(4))
                except ValueError:
                    status_code = 0

                key = (device_uid, att_time_str)
                if key in seen:
                    continue
                seen.add(key)
                unique += 1

                punch_naive = datetime.strptime(att_time_str, "%Y-%m-%d %H:%M:%S")
                if d_from and punch_naive.date() < d_from:
                    continue
                if d_to and punch_naive.date() > d_to:
                    continue
                if device_uid in ignored:
                    continue

                employee = mappings.get(device_uid)
                if employee is None:
                    unknown.add(device_uid)
                    continue

                # Interpret the naive log timestamp in the device clock timezone
                # (_device_tz, resolved once above — may be overridden via
                # --device-tz to reconstruct pre-UTC-8 history), then convert to
                # portal local time (ET) for storage.
                punch_aware = timezone.make_aware(punch_naive, _device_tz)
                punch_local = timezone.localtime(punch_aware)
                # Bucket by the device-local calendar date (matches the live ADMS
                # handler in views.py) so a shift never splits or merges across ET
                # midnight. Store the tz-aware instant so we can sort by absolute
                # time, not naive time-of-day.
                punches[(employee.pk, device_workday(punch_naive, _boundary))].append(
                    (punch_aware, punch_local.time(), status_code)
                )

        self.stdout.write(f"Unique punches parsed : {unique}")
        self.stdout.write(f"(employee, day) groups: {len(punches)}")
        if unknown:
            self.stdout.write(self.style.WARNING(
                f"Unmapped device IDs (skipped): {sorted(unknown)}"
            ))

        emp_by_pk = {e.pk: e for e in mappings.values()}
        created = updated = skipped = 0

        for (emp_pk, punch_date), plist in punches.items():
            employee = emp_by_pk.get(emp_pk)
            if not employee:
                continue
            # Sort by the absolute tz-aware instant (x[0]), NOT the naive
            # time-of-day — otherwise punches that cross ET midnight order wrong
            # and the first/last picks swap check-in and check-out.
            plist.sort(key=lambda x: x[0])
            times = [local_t for _, local_t, _ in plist]
            check_in = times[0]
            check_out = times[-1] if len(times) > 1 else None
            flags = compute_attendance_flags(employee, check_in, check_out)
            note = f"ZKTeco log import ({len(plist)} punch(es))"

            if show_emp is not None and emp_pk == show_emp:
                _pkt = ZoneInfo("Asia/Karachi")
                in_pkt = plist[0][0].astimezone(_pkt).strftime("%a %H:%M")
                out_pkt = plist[-1][0].astimezone(_pkt).strftime("%a %H:%M") if len(plist) > 1 else "—"
                self.stdout.write(
                    f"  {punch_date}  PKT in={in_pkt} out={out_pkt}  "
                    f"(ET in={check_in} out={check_out}, {len(plist)} punch)"
                )

            existing = AttendanceRecord.objects.filter(employee=employee, date=punch_date).first()
            if existing:
                if (existing.leave_request_id
                        or existing.status == AttendanceRecord.StatusChoices.PUBLIC_HOLIDAY):
                    skipped += 1
                    continue
                updated += 1
                if dry:
                    continue
                existing.status = AttendanceRecord.StatusChoices.PRESENT
                existing.check_in = check_in
                # --replace: overwrite check_out even when None (clears stale values
                # from a prior wrong import). Default: only set when we have one.
                if check_out or replace:
                    existing.check_out = check_out
                existing.is_late = flags["is_late"]
                existing.is_early_checkout = flags["is_early_checkout"]
                existing.notes = note
                existing.save(update_fields=[
                    "status", "check_in", "check_out",
                    "is_late", "is_early_checkout", "notes", "updated_at",
                ])
            else:
                created += 1
                if dry:
                    continue
                AttendanceRecord.objects.create(
                    employee=employee, date=punch_date,
                    status=AttendanceRecord.StatusChoices.PRESENT,
                    check_in=check_in, check_out=check_out,
                    is_late=flags["is_late"], is_early_checkout=flags["is_early_checkout"],
                    notes=note,
                )

        prefix = "DRY RUN — would " if dry else ""
        self.stdout.write(self.style.SUCCESS(
            f"\n{prefix}created={created} updated={updated} skipped={skipped}"
        ))
