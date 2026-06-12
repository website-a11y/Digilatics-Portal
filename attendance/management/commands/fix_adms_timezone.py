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

from zoneinfo import ZoneInfo

from django.core.management.base import BaseCommand
from django.utils import timezone

from attendance.models import AttendanceRecord
from attendance.services import compute_attendance_flags

EST = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")


def _to_est(record_date: date, naive_time) -> datetime:
    """Treat a naive time stored on record_date as UTC, return EST datetime."""
    naive_dt = datetime(
        record_date.year, record_date.month, record_date.day,
        naive_time.hour, naive_time.minute, naive_time.second,
    )
    utc_dt = naive_dt.replace(tzinfo=UTC)
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

                # ── check_in UTC date shifted to a different EST date ─────────
                # Example: UTC 01:58 on June 12 → EST 21:58 on June 11
                # The "check_in" punch belongs to the PREVIOUS day as a checkout.
                # The "check_out" punch stays on the current record as the real check_in.
                #
                # Strategy:
                #   1. Find the previous-day record and assign new_ci_time as its checkout.
                #   2. Replace this record's check_in with new_co_time (the real day's start).

                # Step 1 — assign shifted check_in as checkout on new_ci_date
                prev_record = AttendanceRecord.objects.filter(
                    employee=record.employee,
                    date=new_ci_date,
                    status=AttendanceRecord.StatusChoices.PRESENT,
                ).first()
                if prev_record and not prev_record.leave_request_id:
                    if not prev_record.check_out:
                        prev_record.check_out = new_ci_time
                        flags_prev = compute_attendance_flags(
                            record.employee, prev_record.check_in, new_ci_time
                        )
                        prev_record.is_early_checkout = flags_prev["is_early_checkout"]
                        prev_record.save(update_fields=["check_out", "is_early_checkout"])
                        self.stdout.write(
                            f"    → {new_ci_date}: check_out set to {new_ci_time}"
                        )

                # Step 2 — fix current record: real check_in is the checkout's EST time
                if new_co_time and new_co_date == record.date:
                    record.check_in = new_co_time
                    record.check_out = None
                    flags = compute_attendance_flags(record.employee, new_co_time, None)
                    record.is_late = flags["is_late"]
                    record.is_early_checkout = False
                    record.save(update_fields=[
                        "check_in", "check_out", "is_late", "is_early_checkout",
                    ])
                    self.stdout.write(
                        f"    → {record.date}: check_in={new_co_time}, check_out cleared"
                    )
                elif new_co_time is None:
                    # Only one punch that shifted dates — clear it from the wrong record
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
