"""Sidebar badge callbacks for the Leaves app."""


def pending_leave_count(request):
    """Returns the number of pending leave requests — used as a sidebar badge."""
    from leaves.models import LeaveRequest
    return LeaveRequest.objects.filter(status=LeaveRequest.StatusChoices.PENDING).count() or None
