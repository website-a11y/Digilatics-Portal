"""
Django signals that keep attendance records in sync with leave requests,
and propagate Shift time changes to all employees assigned to that shift.
"""
from django.db.models.signals import post_save
from django.dispatch import receiver


@receiver(post_save, sender="leaves.LeaveRequest")
def on_leave_request_saved(sender, instance, **kwargs):
    from attendance.services import sync_leave_request_to_attendance
    sync_leave_request_to_attendance(instance)


@receiver(post_save, sender="attendance.Shift")
def on_shift_saved(sender, instance, **kwargs):
    """
    When a Shift's start/end times change, push those times to every
    EmployeeProfile that references this shift as their shift_master.
    This keeps scheduled_checkin / scheduled_checkout in sync automatically.
    """
    from accounts.models import EmployeeProfile
    EmployeeProfile.objects.filter(shift_master=instance).update(
        scheduled_checkin=instance.start_time,
        scheduled_checkout=instance.end_time,
    )
