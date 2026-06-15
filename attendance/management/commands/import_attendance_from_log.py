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

                # Device sends timestamps in its own clock timezone (PKT = UTC+5).
                # Convert to portal local time (EST/EDT).
                _device_tz = ZoneInfo(settings.ZK_DEVICE.get("device_timezone", "UTC"))
                punch_local = timezone.localtime(
                    timezone.make_aware(punch_naive, _device_tz)
                )
                punches[(employee.pk, punch_local.date())].append(
                    (punch_local.time(), status_code)
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
            plist.sort(key=lambda x: x[0])
            times = [t for t, _ in plist]
            check_in = times[0]
            check_out = times[-1] if len(times) > 1 else None
            flags = compute_attendance_flags(employee, check_in, check_out)
            note = f"ZKTeco log import ({len(plist)} punch(es))"

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
                if check_out:
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
