"""
Scheduled sync command that checks whether it is time to sync based on SyncSchedule.
Run this from an OS scheduler every 5 minutes (cron, Task Scheduler, etc.).
The command will only perform sync when the current time is within the configured
sync window for either schedule entry.

Usage:
    python manage.py sync_if_scheduled
    python manage.py sync_if_scheduled --force
"""
from datetime import datetime
from django.core.management.base import BaseCommand
from django.utils import timezone
from attendance.models import SyncSchedule
from attendance.management.commands.sync_device_attendance import Command as SyncCommand


class Command(BaseCommand):
    help = "Check if it's time to sync and run sync if scheduled"

    def add_arguments(self, parser):
        parser.add_argument(
            "--tolerance-minutes",
            type=int,
            default=5,
            help="Allow this many minutes before/after the scheduled sync time.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Run sync regardless of schedule.",
        )

    def handle(self, *args, **options):
        try:
            schedule = SyncSchedule.objects.first()
            if not schedule or not schedule.is_active:
                self.stdout.write("Sync schedule is not configured or inactive.")
                return
        except Exception:
            self.stdout.write("Could not load sync schedule.")
            return

        # Get current time in Pakistan timezone
        now = timezone.now()
        current_time = now.time()

        # Check if current time matches either sync time
        def time_match(target_time, tolerance_minutes=5):
            diff = abs(
                (current_time.hour * 60 + current_time.minute)
                - (target_time.hour * 60 + target_time.minute)
            )
            return diff <= tolerance_minutes

        tolerance = options.get("tolerance_minutes", 5)
        if not options.get("force"):
            if not (
                time_match(schedule.sync_time_1, tolerance)
                or time_match(schedule.sync_time_2, tolerance)
            ):
                self.stdout.write(
                    f"Not sync time yet. Current: {current_time.strftime('%H:%M')}, "
                    f"Next syncs: {schedule.sync_time_1.strftime('%H:%M')} & {schedule.sync_time_2.strftime('%H:%M')}"
                )
                return

        # Run the sync
        self.stdout.write(
            f"Running sync at {current_time.strftime('%H:%M')} (Pakistan time)..."
        )
        try:
            sync_cmd = SyncCommand()
            sync_cmd.handle()
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Sync failed: {e}"))
