"""
Wipe device-synced attendance records and trigger a full re-sync from the
ZKTeco biometric device.

The device stores all punch history internally.  After the records are deleted
the next time the device polls /iclock/getrequest the server will respond with
a DATA QUERY covering the full date range, the device re-uploads everything,
and the current UTC→EST conversion code stores it correctly.

Usage:
    # Preview — show what would be deleted, nothing saved
    python manage.py reset_and_resync --dry-run

    # Delete records from the last 30 days and trigger device re-sync
    python manage.py reset_and_resync

    # Delete ALL device-synced records ever (use with care)
    python manage.py reset_and_resync --all

    # Delete from a specific date onwards
    python manage.py reset_and_resync --from-date 2026-01-01
"""
import os
from datetime import date, timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from attendance.models import AttendanceRecord
from attendance.views import _adms_flag_dir


_FULL_SYNC_FLAG = "full_sync_from"


def write_full_sync_flag(from_date: date):
    """Write a flag file telling iclock_getrequest to query from from_date."""
    path = os.path.join(_adms_flag_dir(), _FULL_SYNC_FLAG)
    with open(path, "w") as f:
        f.write(from_date.isoformat())


class Command(BaseCommand):
    help = "Delete device-synced attendance records and trigger full re-sync from device"

    def add_arguments(self, parser):
        parser.add_argument(
            "--from-date",
            type=str,
            default=None,
            help="Delete records from this date onwards YYYY-MM-DD (default: 90 days ago)",
        )
        parser.add_argument(
            "--all",
            action="store_true",
            help="Delete ALL device-synced records regardless of date",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be deleted without making any changes",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        delete_all = options["all"]
        today = timezone.localdate()

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN — nothing will be changed\n"))

        # Build queryset — only delete device-synced records, never leave records
        qs = AttendanceRecord.objects.filter(
            notes__icontains="ZKTeco",
            leave_request__isnull=True,
        ).exclude(
            status=AttendanceRecord.StatusChoices.PUBLIC_HOLIDAY,
        )

        if delete_all:
            from_date = date(2000, 1, 1)
            self.stdout.write("Scope: ALL device-synced records")
        else:
            if options["from_date"]:
                from_date = date.fromisoformat(options["from_date"])
            else:
                from_date = today - timedelta(days=90)
            qs = qs.filter(date__gte=from_date)
            self.stdout.write(f"Scope: device-synced records from {from_date} onwards")

        count = qs.count()
        self.stdout.write(f"Records to delete: {count}")

        if count == 0:
            self.stdout.write("Nothing to delete.")
            return

        # Show a sample
        for rec in qs.order_by("date", "employee__full_name")[:10]:
            self.stdout.write(
                f"  {rec.date}  {rec.employee.full_name:30s}  "
                f"In:{str(rec.check_in or '—'):8s}  Out:{str(rec.check_out or '—')}"
            )
        if count > 10:
            self.stdout.write(f"  ... and {count - 10} more")

        if dry_run:
            self.stdout.write(self.style.WARNING(
                f"\nDRY RUN complete. Re-run without --dry-run to delete {count} record(s)."
            ))
            return

        # Delete
        qs.delete()
        self.stdout.write(self.style.SUCCESS(f"\nDeleted {count} record(s)."))

        # Write flag so iclock_getrequest sends a full DATA QUERY on next device poll
        write_full_sync_flag(from_date)
        self.stdout.write(self.style.SUCCESS(
            f"Full-sync flag written — device will re-upload all punches from "
            f"{from_date} on its next poll (within ~1 minute)."
        ))
