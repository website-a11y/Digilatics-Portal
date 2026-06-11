"""
Scheduled sync command that checks whether it is time to sync based on SyncSchedule.
Run this from an OS scheduler every 5 minutes (cron, Task Scheduler, etc.).
The command will only perform sync when the current time is within the configured
sync window for either schedule entry.

Usage:
    python manage.py sync_if_scheduled
    python manage.py sync_if_scheduled --force
"""
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.utils import timezone
from attendance.models import SyncSchedule


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

        # Use local time so schedule times (stored as local clock times) match correctly
        current_time = timezone.localtime(timezone.now()).time()

        def time_match(target_time, tolerance_minutes):
            diff = abs(
                (current_time.hour * 60 + current_time.minute)
                - (target_time.hour * 60 + target_time.minute)
            )
            return diff <= tolerance_minutes

        tolerance = options["tolerance_minutes"]
        if not options["force"]:
            t1_match = time_match(schedule.sync_time_1, tolerance)
            t2_match = (
                time_match(schedule.sync_time_2, tolerance)
                if schedule.sync_time_2
                else False
            )
            if not (t1_match or t2_match):
                self.stdout.write(
                    f"Not sync time yet. Current: {current_time.strftime('%H:%M')}, "
                    f"Sync 1: {schedule.sync_time_1.strftime('%H:%M')}"
                    + (
                        f", Sync 2: {schedule.sync_time_2.strftime('%H:%M')}"
                        if schedule.sync_time_2
                        else ""
                    )
                )
                return

        self.stdout.write(
            f"Running scheduled sync at {current_time.strftime('%H:%M')}..."
        )
        try:
            call_command("sync_device_attendance", stdout=self.stdout)
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Sync failed: {e}"))
