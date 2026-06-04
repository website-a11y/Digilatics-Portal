"""
Django signals that keep attendance records in sync with leave requests.

Triggered on every LeaveRequest save (individual edits through the admin
or programmatic saves).  Bulk queryset.update() calls in admin actions are
handled separately by calling sync_leave_request_to_attendance() explicitly.
"""
from django.db.models.signals import post_save
from django.dispatch import receiver


@receiver(post_save, sender="leaves.LeaveRequest")
def on_leave_request_saved(sender, instance, **kwargs):
    from attendance.services import sync_leave_request_to_attendance

    sync_leave_request_to_attendance(instance)
