"""
One-time fix: shift start/end times were entered by admins in Pakistan Standard
Time (PKT, UTC+5).  Now that the entire portal runs on Eastern Time (EST/EDT),
those times must be converted so late-arrival and early-checkout detection works
correctly.

Conversion: PKT → EST   (PKT is UTC+5, EDT is UTC-4  →  9-hour difference)
Example:  3:00 PM PKT  →  6:00 AM EDT
          12:00 AM PKT →  3:00 PM EDT (previous day in UTC, same calendar day in context)

Usage:
    # Preview — nothing saved
    python manage.py fix_shift_timezone --dry-run

    # Apply to all shifts and re-sync employee scheduled times
    python manage.py fix_shift_timezone
"""
from datetime import datetime, date

import pytz

from django.core.management.base import BaseCommand
from django.utils import timezone

PKT = pytz.timezone("Asia/Karachi")   # UTC+5
EST = pytz.timezone("America/New_York")

# Use a fixed reference date so the conversion is deterministic regardless of
# when this command is run.  DST rules for 2026 apply (EDT = UTC-4 in summer).
_REF_DATE = date(2026, 6, 1)


def _pkt_to_est(naive_time):
    """Convert a naive time assumed to be PKT to a naive EST time."""
    dt_pkt = PKT.localize(datetime(_REF_DATE.year, _REF_DATE.month, _REF_DATE.day,
                                   naive_time.hour, naive_time.minute, naive_time.second))
    dt_est = dt_pkt.astimezone(EST)
    return dt_est.time().replace(tzinfo=None)


class Command(BaseCommand):
    help = "Convert Shift start/end times from PKT (UTC+5) to Eastern Time (EST/EDT)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what would change without saving anything",
        )

    def handle(self, *args, **options):
        from attendance.models import Shift
        from accounts.models import EmployeeProfile

        dry_run = options["dry_run"]
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN — nothing will be saved\n"))

        shifts = Shift.objects.all()
        if not shifts.exists():
            self.stdout.write("No shifts found.")
            return

        fixed_shifts = 0
        for shift in shifts:
            old_start = shift.start_time
            old_end = shift.end_time
            new_start = _pkt_to_est(old_start)
            new_end = _pkt_to_est(old_end)

            self.stdout.write(
                f"  Shift '{shift.name}': "
                f"{old_start.strftime('%I:%M %p')} PKT → {new_start.strftime('%I:%M %p')} EST  |  "
                f"{old_end.strftime('%I:%M %p')} PKT → {new_end.strftime('%I:%M %p')} EST"
            )

            if not dry_run:
                shift.start_time = new_start
                shift.end_time = new_end
                shift.save(update_fields=["start_time", "end_time"])
                fixed_shifts += 1

        if not dry_run:
            self.stdout.write(self.style.SUCCESS(f"\nUpdated {fixed_shifts} shift(s)."))

            # Re-sync every employee whose scheduled times come from a shift master
            synced = 0
            for emp in EmployeeProfile.objects.filter(shift_master__isnull=False).select_related("shift_master"):
                emp.scheduled_checkin = emp.shift_master.start_time
                emp.scheduled_checkout = emp.shift_master.end_time
                emp.save(update_fields=["scheduled_checkin", "scheduled_checkout"])
                synced += 1

            # Also convert employees with manually-set times (no shift master)
            manual = 0
            for emp in EmployeeProfile.objects.filter(shift_master__isnull=True):
                changed = False
                if emp.scheduled_checkin:
                    emp.scheduled_checkin = _pkt_to_est(emp.scheduled_checkin)
                    changed = True
                if emp.scheduled_checkout:
                    emp.scheduled_checkout = _pkt_to_est(emp.scheduled_checkout)
                    changed = True
                if changed:
                    emp.save(update_fields=["scheduled_checkin", "scheduled_checkout"])
                    manual += 1

            self.stdout.write(self.style.SUCCESS(
                f"Synced {synced} shift-linked employee(s), "
                f"converted {manual} manually-scheduled employee(s)."
            ))
        else:
            self.stdout.write("\nRe-run without --dry-run to apply changes.")
