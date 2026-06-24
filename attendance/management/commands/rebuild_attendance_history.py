"""
Rebuild historical AttendanceRecords from the raw ZKTeco log, correctly across
device-clock eras.

WHY THIS EXISTS
───────────────
The biometric device's clock offset was changed several times during migration
(e.g. UTC → UTC-8 → PKT). Raw ATT_TIME values in zkteco_debug.log therefore mean
different wall-clock instants in different date ranges. Any reconstruction that
assumes a single device timezone mis-converts the eras it doesn't match, which is
what produced wrong times, wrong dates, and swapped check-in/out for overnight
shifts.

THE CORRECT, ERA-INDEPENDENT ALGORITHM
──────────────────────────────────────
Employees are physically in one real local zone (--local-tz, default Asia/Karachi
= PKT). Every punch maps to a fixed real instant once we know which clock the
device was on when it was recorded:

    instant   = make_aware(ATT_TIME, era_zone_for_that_date)
    pkt_local = instant in --local-tz            (employees' real local time)
    workday   = device_workday(pkt_local)        (PKT date, noon cutoff for
                                                   overnight shifts)
    stored    = instant in America/New_York       (times are stored as ET, like
                                                   the live ADMS pipeline)

check_in = earliest instant of the workday, check_out = latest. Sorting is by the
absolute instant, never naive time-of-day, so midnight-crossing punches never
swap. This reproduces today's live pipeline EXACTLY for the current (PKT) era and
extends it correctly to the older eras.

ERA MAP
───────
An "era" is a date on/after which the device clock ran on a given zone. Supply it
explicitly once you've read the boundaries from `diagnose_punch_eras`:

    --era 2026-06-19:UTC-8 --era 2026-06-23:Asia/Karachi --base-tz UTC

means: punches before 2026-06-19 → UTC, 06-19..06-22 → UTC-8, 06-23+ → PKT.
Zone tokens accept IANA names (Asia/Karachi) or fixed offsets (UTC, UTC-8, UTC+5).

Read the boundaries from `diagnose_punch_eras` (its per-employee raw view shows
the step clearly for the afternoon/overnight shift pattern). Era zones are NOT
auto-guessed — payroll data is too important to hinge on a heuristic; you state
them explicitly and verify the dry-run before applying.

SAFETY
──────
Dry-run by default — writes NOTHING unless you pass --apply. The dry-run prints a
per-day OLD→NEW comparison (use --emp to focus the spot-check). Records tied to a
leave request or a public holiday are never touched.

USAGE
─────
    # 1) Inspect what would change, focused on a couple of known employees:
    python manage.py rebuild_attendance_history --auto --emp 10001 --emp 10005

    # 2) With explicit, verified eras and an apply:
    python manage.py rebuild_attendance_history \
        --era 2026-06-19:UTC-8 --era 2026-06-23:Asia/Karachi --base-tz UTC \
        --from 2026-02-01 --to 2026-06-23 --apply
"""
import re
from collections import defaultdict
from datetime import datetime, date as date_cls, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone as dj_tz

from attendance.models import AttendanceRecord, DeviceEmployee
from attendance.services import compute_attendance_flags
from attendance.tz_utils import device_workday, WORKDAY_BOUNDARY_HOUR

PUNCH_RE = re.compile(
    r"(\d{1,7})\s+(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+(\d+)\s+(-?\d+)"
)
_STORED_TZ = ZoneInfo("America/New_York")  # times are stored as ET


def _parse_zone(token: str):
    """Accept an IANA name (Asia/Karachi) or a fixed offset (UTC, UTC-8, UTC+5)."""
    token = token.strip()
    m = re.fullmatch(r"UTC([+-]\d{1,2})?", token, re.IGNORECASE)
    if m:
        hrs = int(m.group(1)) if m.group(1) else 0
        # timezone(timedelta) — fixed offset, DST-free, exactly what an old device
        # clock pinned to "TimeZone=N" behaves like.
        from datetime import timezone as _tz
        return _tz(timedelta(hours=hrs))
    try:
        return ZoneInfo(token)
    except ZoneInfoNotFoundError:
        raise CommandError(f"Unknown timezone token: {token!r}")


class Command(BaseCommand):
    help = "Rebuild historical attendance from the raw log, correct across device-clock eras"

    def add_arguments(self, parser):
        parser.add_argument("--log", default="zkteco_debug.log", help="Path to the debug log")
        parser.add_argument("--local-tz", default=None,
                            help="Employees' real local zone (default: the Device Timezone "
                                 "setting, i.e. the current era's zone)")
        parser.add_argument("--base-tz", default=None,
                            help="Device clock zone BEFORE the first --era boundary")
        parser.add_argument("--era", dest="eras", action="append", default=[],
                            help="'YYYY-MM-DD:ZONE' — on/after this date the device clock "
                                 "ran on ZONE (repeatable)")
        parser.add_argument("--emp", dest="emps", action="append", type=int, default=[],
                            help="Focus the OLD→NEW comparison on this DEVICE id (repeatable)")
        parser.add_argument("--from", dest="from_date", default=None,
                            help="Only rebuild workdays on/after this date YYYY-MM-DD")
        parser.add_argument("--to", dest="to_date", default=None,
                            help="Only rebuild workdays on/before this date YYYY-MM-DD")
        parser.add_argument("--apply", action="store_true",
                            help="Actually write records (default: dry-run, writes nothing)")

    # ── era resolution ─────────────────────────────────────────────────────
    def _build_era_map(self, opts, local_tz):
        """Return a sorted list of (start_date_or_None, zone). The first entry's
        start is None meaning 'from the beginning of time'."""
        eras = []
        base = _parse_zone(opts["base_tz"]) if opts["base_tz"] else local_tz
        eras.append((None, base))
        for spec in opts["eras"]:
            try:
                d_str, z_str = spec.split(":", 1)
                d = date_cls.fromisoformat(d_str.strip())
            except ValueError:
                raise CommandError(f"Bad --era {spec!r}; expected 'YYYY-MM-DD:ZONE'")
            eras.append((d, _parse_zone(z_str)))
        eras.sort(key=lambda e: (e[0] is not None, e[0]))
        return eras

    @staticmethod
    def _zone_for(raw_date, era_map):
        zone = era_map[0][1]
        for start, z in era_map[1:]:
            if raw_date >= start:
                zone = z
        return zone

    def handle(self, *args, **opts):
        try:
            d_from = date_cls.fromisoformat(opts["from_date"]) if opts["from_date"] else None
            d_to = date_cls.fromisoformat(opts["to_date"]) if opts["to_date"] else None
        except ValueError:
            raise CommandError("Dates must be YYYY-MM-DD")

        apply = opts["apply"]
        if not apply:
            self.stdout.write(self.style.WARNING("DRY RUN — no records will be written\n"))

        from attendance.models import SystemSetting
        local_name = opts["local_tz"] or SystemSetting.get_device_timezone()
        local_tz = _parse_zone(local_name)
        self.stdout.write(f"Employees' real local zone: {local_name}")

        era_map = self._build_era_map(opts, local_tz)
        self.stdout.write("Era map (device clock by date):")
        for start, z in era_map:
            self.stdout.write(f"  {start or 'beginning'} → {z}")

        ignored = {int(x) for x in getattr(settings, "ZK_IGNORED_DEVICE_IDS", [])}
        mappings = {dm.device_user_id: dm.employee
                    for dm in DeviceEmployee.objects.select_related("employee")}
        focus = set(opts["emps"])

        # ── Parse + dedup the log ───────────────────────────────────────────
        try:
            fh = open(opts["log"], "r", encoding="utf-8", errors="replace")
        except OSError as exc:
            raise CommandError(f"Cannot open log: {exc}")

        seen = set()
        raw_by_day = defaultdict(list)   # raw_date -> [(uid, naive_dt, status)]
        unique = 0
        with fh:
            for line in fh:
                m = PUNCH_RE.search(line)
                if not m:
                    continue
                uid = int(m.group(1))
                att = m.group(2)
                key = (uid, att)
                if key in seen:
                    continue
                seen.add(key)
                try:
                    dt = datetime.strptime(att, "%Y-%m-%d %H:%M:%S")
                    status = int(m.group(4))
                except ValueError:
                    continue
                if uid in ignored or uid not in mappings:
                    continue
                unique += 1
                raw_by_day[dt.date()].append((uid, dt, status))

        def zone_for(raw_date):
            return self._zone_for(raw_date, era_map)

        # ── Build (emp, workday) → punches, converting each via its era zone ─
        groups = defaultdict(list)   # (emp_pk, workday) -> [(instant, et_time, status)]
        for rd, items in raw_by_day.items():
            zone = zone_for(rd)
            for uid, naive_dt, status in items:
                instant = naive_dt.replace(tzinfo=zone)
                local_dt = instant.astimezone(local_tz)
                workday = device_workday(local_dt, WORKDAY_BOUNDARY_HOUR)
                if d_from and workday < d_from:
                    continue
                if d_to and workday > d_to:
                    continue
                emp = mappings[uid]
                et_time = instant.astimezone(_STORED_TZ).time()
                groups[(emp.pk, workday)].append((instant, et_time, status, uid))

        self.stdout.write(self.style.SUCCESS(
            f"\nUnique punches: {unique}   (employee, workday) groups: {len(groups)}"))

        emp_by_pk = {e.pk: e for e in mappings.values()}
        created = updated = skipped = unchanged = 0
        show_header = True

        for (emp_pk, workday), plist in sorted(groups.items()):
            employee = emp_by_pk.get(emp_pk)
            if not employee:
                continue
            plist.sort(key=lambda x: x[0])             # by absolute instant
            check_in = plist[0][1]
            check_out = plist[-1][1] if len(plist) > 1 else None
            flags = compute_attendance_flags(employee, check_in, check_out)
            note = f"Rebuilt from device log ({len(plist)} punch(es))"

            existing = AttendanceRecord.objects.filter(
                employee=employee, date=workday).first()

            # Never disturb leave / holiday records.
            if existing and (existing.leave_request_id or existing.status ==
                             AttendanceRecord.StatusChoices.PUBLIC_HOLIDAY):
                skipped += 1
                continue

            old_in = existing.check_in if existing else None
            old_out = existing.check_out if existing else None
            changed = (not existing or old_in != check_in or old_out != check_out)

            # ── spot-check comparison (focused employees, or all if none) ───
            uid = plist[0][3]
            if (not focus) or (uid in focus):
                if show_header:
                    self.stdout.write(self.style.SUCCESS(
                        "\n=== OLD → NEW (ET times) ==="))
                    self.stdout.write(
                        f"{'emp':<22}{'date':<12}{'OLD in/out':<20}{'NEW in/out':<20}{'Δ'}")
                    show_header = False
                flag = "CHANGED" if changed else ""
                self.stdout.write(
                    f"{employee.full_name[:21]:<22}{str(workday):<12}"
                    f"{str(old_in)+'/'+str(old_out):<20}"
                    f"{str(check_in)+'/'+str(check_out):<20}{flag}"
                )

            if not changed:
                unchanged += 1
                continue

            if existing:
                updated += 1
                if apply:
                    existing.status = AttendanceRecord.StatusChoices.PRESENT
                    existing.check_in = check_in
                    existing.check_out = check_out
                    existing.is_late = flags["is_late"]
                    existing.is_early_checkout = flags["is_early_checkout"]
                    existing.notes = note
                    existing.save(update_fields=[
                        "status", "check_in", "check_out",
                        "is_late", "is_early_checkout", "notes", "updated_at"])
            else:
                created += 1
                if apply:
                    AttendanceRecord.objects.create(
                        employee=employee, date=workday,
                        status=AttendanceRecord.StatusChoices.PRESENT,
                        check_in=check_in, check_out=check_out,
                        is_late=flags["is_late"],
                        is_early_checkout=flags["is_early_checkout"], notes=note)

        prefix = "" if apply else "DRY RUN — would "
        self.stdout.write(self.style.SUCCESS(
            f"\n{prefix}created={created} updated={updated} "
            f"unchanged={unchanged} skipped(leave/holiday)={skipped}"))
        if not apply:
            self.stdout.write("Re-run with --apply once the OLD→NEW comparison looks right.")
