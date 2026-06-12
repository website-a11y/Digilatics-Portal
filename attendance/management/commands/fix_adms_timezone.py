"""
One-time fix: attendance records received via ADMS after the device was switched
to TimeZone=0 (UTC) but BEFORE the UTC→EST conversion code was deployed were
stored with raw UTC times.  This command re-interprets check_in / check_out on
those records as UTC, converts them to Eastern Time, and re-buckets by the
correct EST calendar date.

Usage:
    # Preview — no changes written
    python manage.py fix_adms_timezone --dry-run

    # Fix all ADMS records from last 7 days (default)
    python manage.py fix_adms_timezone

    # Fix a specific range
    python manage.py fix_adms_timezone --from-date 2026-06-01 --to-date 2026-06-12

    # Fix ALL ADMS records ever stored (use with care)
    python manage.py fix_adms_timezone --from-date 2026-01-01
"""
from datetime import date, datetime, timedelta

import pytz

from django.core.management.base import BaseCommand
from django.utils import timezone

from attendance.models import AttendanceRecord
from attendance.services import compute_attendance_flags

EST = pytz.timezone("America/New_York")


def _to_est(record_date: date, naive_time) -> datetime:
    """Treat a naive time stored on record_date as UTC, return EST datetime."""
    naive_dt = datetime(
        record_date.year, record_date.month, record_date.day,
        naive_time.hour, naive_time.minute, naive_time.second,
    )
    utc_dt = pytz.utc.localize(naive_dt)
    return utc_dt.astimezone(EST)


class Command(BaseCommand):
    help = "Convert ADMS attendance times stored in UTC to Eastern Time (EST/EDT)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--from-date",
            type=str,
            default=None,
            help="Start of date range YYYY-MM-DD (default: 7 days ago)",
        )
        parser.add_argument(
            "--to-date",
            type=str,
            default=None,
            help="End of date range YYYY-MM-DD (default: today)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what would change without saving anything",
        )

    def handle(self, *args, **options):
        today = timezone.localdate()
        from_date = (
            date.fromisoformat(options["from_date"])
            if options["from_date"]
            else today - timedelta(days=7)
        )
        to_date = (
            date.fromisoformat(options["to_date"])
            if options["to_date"]
            else today
        )
        dry_run = options["dry_run"]

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN — nothing will be saved"))

        qs = (
            AttendanceRecord.objects
            .filter(date__gte=from_date, date__lte=to_date, notes__icontains="ZKTeco ADMS")
            .select_related("employee")
            .order_by("date", "employee")
        )

        total = qs.count()
        self.stdout.write(f"Found {total} ADMS record(s) in {from_date} → {to_date}")

        fixed = skipped = errors = 0

        for record in qs:
            if not record.check_in:
                skipped += 1
                continue

            try:
                ci_est = _to_est(record.date, record.check_in)
                co_est = _to_est(record.date, record.check_out) if record.check_out else None

                new_ci_date = ci_est.date()
                new_ci_time = ci_est.time().replace(tzinfo=None)

                # check_out may fall on a different date (e.g. evening shift)
                new_co_date = co_est.date() if co_est else None
                new_co_time = co_est.time().replace(tzinfo=None) if co_est else None

                date_shifted = new_ci_date != record.date

                self.stdout.write(
                    f"  {record.employee} | orig date={record.date} "
                    f"In={record.check_in} Out={record.check_out} → "
                    f"date={new_ci_date} In={new_ci_time} Out={new_co_time}"
                    + (" [DATE SHIFTED]" if date_shifted else "")
                )

                if dry_run:
                    continue

                # ── Same date for both in/out ─────────────────────────────────
                if not date_shifted:
                    record.check_in = new_ci_time
                    record.check_out = new_co_time
                    flags = compute_attendance_flags(record.employee, new_ci_time, new_co_time)
                    record.is_late = flags["is_late"]
                    record.is_early_checkout = flags["is_early_checkout"]
                    record.save(update_fields=[
                        "check_in", "check_out", "is_late", "is_early_checkout",
                    ])
                    fixed += 1
                    continue

                # ── check_in shifted to a different (usually previous) date ──
                # The check_in belongs on new_ci_date; check_out stays on its date.
                # Strategy:
                #   • For the original record (record.date): replace check_in
                #     with check_out EST (real start of that work-day), clear
                #     check_out if it belongs on yet another date.
                #   • For new_ci_date record: set check_out = new_ci_time
                #     (the punch that belongs to the previous day).

                # Handle the day the check_in actually belongs to
                prev_record = AttendanceRecord.objects.filter(
                    employee=record.employee, date=new_ci_date
                ).first()
                if prev_record:
                    # Update that record's check_out with the shifted check_in time
                    if not prev_record.check_out:
                        prev_record.check_out = new_ci_time
                        prev_record.save(update_fields=["check_out"])
                        self.stdout.write(
                            f"    → updated {new_ci_date} check_out={new_ci_time}"
                        )

                # Fix the current record: its real check_in is the check_out EST time
                if new_co_time and (new_co_date == record.date):
                    record.check_in = new_co_time
                    record.check_out = None
                    flags = compute_attendance_flags(record.employee, new_co_time, None)
                    record.is_late = flags["is_late"]
                    record.is_early_checkout = False
                    record.save(update_fields=[
                        "check_in", "check_out", "is_late", "is_early_checkout",
                    ])
                    self.stdout.write(
                        f"    → updated {record.date} check_in={new_co_time} check_out=None"
                    )
                elif new_co_time is None:
                    # No check_out; just clear the wrong check_in
                    record.check_in = None
                    record.save(update_fields=["check_in"])

                fixed += 1

            except Exception as exc:
                self.stdout.write(
                    self.style.ERROR(f"  ERROR on {record.employee} {record.date}: {exc}")
                )
                errors += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"\n{'Would fix' if dry_run else 'Fixed'} {fixed} record(s), "
                f"skipped {skipped}, errors {errors}"
            )
        )
        if dry_run:
            self.stdout.write("Re-run without --dry-run to apply changes.")
