"""
Wipe device-synced attendance records and trigger a full re-sync from the
ZKTeco biometric device.

The device stores all punch history internally.  After the records are deleted
the next time the device polls /iclock/cdata the server returns ATTLOGStamp=0
in the handshake, the device re-uploads everything, and the UTC→EST conversion
code stores it correctly.

Usage:
    # Preview — show what would be deleted, nothing saved
    python manage.py reset_and_resync --dry-run

    # Delete records from the last 90 days and trigger device re-sync
    python manage.py reset_and_resync

    # Delete ALL device-synced records ever (use with care)
    python manage.py reset_and_resync --all

    # Delete from a specific date onwards
    python manage.py reset_and_resync --from-date 2026-01-01

    # Just trigger a full re-upload WITHOUT deleting any records
    python manage.py reset_and_resync --force-sync
"""
from datetime import date, timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from attendance.models import AttendanceRecord, DeviceSyncFlag


def write_full_sync_flag(from_date: date):
    """Record (in the DB) that the device should re-upload all punches.

    Stored in the database rather than a file so the web process (different OS
    user) reliably sees it — a shared file kept hitting permission problems.
    """
    DeviceSyncFlag.request(from_date)


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
        parser.add_argument(
            "--force-sync",
            action="store_true",
            help="Write the re-sync flag WITHOUT deleting any records (re-upload all punches from device)",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        delete_all = options["all"]
        force_sync = options["force_sync"]
        today = timezone.localdate()

        # --force-sync: just write the flag, skip deletion entirely
        if force_sync:
            if dry_run:
                self.stdout.write(self.style.WARNING(
                    "DRY RUN — would write full-sync flag (no records deleted)"
                ))
                return
            from_date = date(2000, 1, 1)
            write_full_sync_flag(from_date)
            self.stdout.write(self.style.SUCCESS(
                "Full-sync flag written — device will re-upload ALL punches on its next "
                "poll (within ~1 minute). No records were deleted."
            ))
            return

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
            # Still write the flag so the device re-uploads (useful after a failed sync)
            if not dry_run:
                write_full_sync_flag(from_date)
                self.stdout.write(self.style.SUCCESS(
                    f"Full-sync flag written — device will re-upload all punches from "
                    f"{from_date} on its next poll (within ~1 minute)."
                ))
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

        # Write flag so next handshake returns ATTLOGStamp=0
        write_full_sync_flag(from_date)
        self.stdout.write(self.style.SUCCESS(
            f"Full-sync flag written — device will re-upload all punches from "
            f"{from_date} on its next poll (within ~1 minute)."
        ))
