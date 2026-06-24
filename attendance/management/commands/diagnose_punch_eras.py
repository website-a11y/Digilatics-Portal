"""
READ-ONLY diagnostic: surface device-clock "eras" from the raw ZKTeco log.

Writes NOTHING — no DB changes, no file changes. It parses zkteco_debug.log,
dedups the heavy handshake re-dumps, and prints the RAW (uninterpreted) punch
time-of-day per employee per day. Because real employees punch at consistent
local times, a device-clock change shows up as a sudden step in the raw
time-of-day. These are afternoon/overnight shifts (check-in ~16:00 PKT,
check-out ~01:00 PKT next day), so the per-employee view below is the clearest
read: when the device clock changes, that employee's whole daily pattern shifts
by the offset delta on a specific date. Reading those steps tells us the era
boundary DATES and the OFFSET in each era — the inputs needed to drive
rebuild_attendance_history --era/--base-tz per era.

Usage:
    # Overall coverage + a global daily earliest-punch trend (find the steps):
    python manage.py diagnose_punch_eras

    # Focus on specific regular employees by DEVICE id (clearest signal):
    python manage.py diagnose_punch_eras --emp 10001 --emp 10005

    # Narrow to a window while zeroing in on a boundary:
    python manage.py diagnose_punch_eras --emp 10001 --from 2026-06-10 --to 2026-06-25

    # Point at a specific log copy:
    python manage.py diagnose_punch_eras --log /home/funnelatics-hris/htdocs/.../zkteco_debug.log
"""
import re
import statistics
from collections import defaultdict
from datetime import datetime, date as date_cls

from django.core.management.base import BaseCommand, CommandError

from attendance.models import DeviceEmployee

# Same matcher import_attendance_from_log uses: BIO_ID ATT_TIME VERIFY STATUS,
# tolerant of a leading "BODY  : " prefix.
PUNCH_RE = re.compile(
    r"(\d{1,7})\s+(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+(\d+)\s+(-?\d+)"
)


class Command(BaseCommand):
    help = "READ-ONLY: show raw punch time-of-day per day to locate device-clock eras"

    def add_arguments(self, parser):
        parser.add_argument("--log", default="zkteco_debug.log", help="Path to the debug log")
        parser.add_argument("--emp", dest="emps", action="append", type=int, default=[],
                            help="Focus on this DEVICE user id (repeatable)")
        parser.add_argument("--from", dest="from_date", default=None,
                            help="Only consider punches on/after this RAW date YYYY-MM-DD")
        parser.add_argument("--to", dest="to_date", default=None,
                            help="Only consider punches on/before this RAW date YYYY-MM-DD")

    def handle(self, *args, **opts):
        try:
            d_from = date_cls.fromisoformat(opts["from_date"]) if opts["from_date"] else None
            d_to = date_cls.fromisoformat(opts["to_date"]) if opts["to_date"] else None
        except ValueError:
            raise CommandError("Dates must be YYYY-MM-DD")

        try:
            fh = open(opts["log"], "r", encoding="utf-8", errors="replace")
        except OSError as exc:
            raise CommandError(f"Cannot open log: {exc}")

        focus = set(opts["emps"])
        mappings = {dm.device_user_id: dm.employee
                    for dm in DeviceEmployee.objects.select_related("employee")}

        seen = set()                                  # (uid, att_time_str) dedup
        # per-uid: date -> list[datetime]
        per_emp = defaultdict(lambda: defaultdict(list))
        # global: date -> list of earliest-per-uid hour fractions (for trend)
        all_punches = []                              # (uid, datetime)
        min_dt = max_dt = None
        total_unique = 0

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
                except ValueError:
                    continue
                if d_from and dt.date() < d_from:
                    continue
                if d_to and dt.date() > d_to:
                    continue
                total_unique += 1
                min_dt = dt if (min_dt is None or dt < min_dt) else min_dt
                max_dt = dt if (max_dt is None or dt > max_dt) else max_dt
                all_punches.append((uid, dt))
                if not focus or uid in focus:
                    per_emp[uid][dt.date()].append(dt)

        if total_unique == 0:
            self.stdout.write(self.style.WARNING("No punches matched in the log."))
            return

        # ── Coverage summary ────────────────────────────────────────────────
        self.stdout.write(self.style.SUCCESS("=== LOG COVERAGE (raw, uninterpreted) ==="))
        self.stdout.write(f"Unique punches : {total_unique}")
        self.stdout.write(f"Date range     : {min_dt.date()}  →  {max_dt.date()}")
        self.stdout.write(f"Distinct device IDs: {len({u for u, _ in all_punches})}")

        # ── Global daily earliest-punch trend: the step pattern shows eras ──
        # For each calendar date, the median of each device's earliest punch
        # hour. A jump in this number across consecutive dates = a clock change.
        earliest_by_uid_day = defaultdict(dict)       # uid -> date -> earliest dt
        for uid, dt in all_punches:
            cur = earliest_by_uid_day[uid].get(dt.date())
            if cur is None or dt < cur:
                earliest_by_uid_day[uid][dt.date()] = dt
        day_hours = defaultdict(list)                 # date -> [hour floats]
        for uid, daymap in earliest_by_uid_day.items():
            for d, dt in daymap.items():
                day_hours[d].append(dt.hour + dt.minute / 60.0)

        self.stdout.write(self.style.SUCCESS(
            "\n=== DAILY EARLIEST-PUNCH HOUR (median across employees) ==="))
        self.stdout.write("A sudden step in 'med_h' marks a device-clock change.\n")
        self.stdout.write(f"{'date':<12}{'n_emp':>6}{'med_h':>8}{'min_h':>8}{'max_h':>8}")
        for d in sorted(day_hours):
            hrs = day_hours[d]
            self.stdout.write(
                f"{str(d):<12}{len(hrs):>6}{statistics.median(hrs):>8.1f}"
                f"{min(hrs):>8.1f}{max(hrs):>8.1f}"
            )

        # ── Per-focused-employee raw day-by-day punches ─────────────────────
        for uid in sorted(per_emp):
            emp = mappings.get(uid)
            name = emp.full_name if emp else "(UNMAPPED)"
            self.stdout.write(self.style.SUCCESS(
                f"\n=== DEVICE {uid} — {name} (raw device times) ==="))
            self.stdout.write(f"{'date':<12}{'first':>8}{'last':>8}  all_times")
            for d in sorted(per_emp[uid]):
                times = sorted(per_emp[uid][d])
                first = times[0].strftime("%H:%M")
                last = times[-1].strftime("%H:%M") if len(times) > 1 else "—"
                joined = " ".join(t.strftime("%H:%M") for t in times)
                self.stdout.write(f"{str(d):<12}{first:>8}{last:>8}  {joined}")

        self.stdout.write(self.style.WARNING(
            "\nThis command made NO changes. Read the step dates + offsets above, "
            "then feed them to rebuild_attendance_history as --era 'YYYY-MM-DD:ZONE' "
            "(and --base-tz for the era before the first boundary)."
        ))
