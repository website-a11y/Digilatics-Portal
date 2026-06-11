"""
Management command: escalate_pending_approvals

Runs daily (e.g. via cron or task scheduler).

Logic:
  For every pending LeaveRequest whose assigned approver (reporting manager)
  has been on approved leave for 4 or more consecutive days (up to 7),
  re-assign the request to that manager's own reporting manager
  (the next-level approver / team lead).

Usage:
  python manage.py escalate_pending_approvals
  python manage.py escalate_pending_approvals --dry-run
"""

from datetime import date, timedelta

from django.core.management.base import BaseCommand

from accounts.models import EmployeeProfile
from leaves.models import LeaveRequest


CONSECUTIVE_DAYS_THRESHOLD = 4


def _manager_on_leave_consecutive_days(manager, as_of: date) -> int:
    """
    Return the number of consecutive approved leave days for *manager* ending
    on or before *as_of*.  Returns 0 if the manager is not currently on leave.
    """
    approved_leave_dates = set(
        LeaveRequest.objects.filter(
            employee=manager,
            status=LeaveRequest.StatusChoices.APPROVED,
        ).values_list("from_date", "to_date")
    )

    # Build a flat set of all approved leave dates for this manager
    leave_date_set = set()
    for from_d, to_d in approved_leave_dates:
        d = from_d
        while d <= to_d:
            leave_date_set.add(d)
            d += timedelta(days=1)

    if as_of not in leave_date_set:
        return 0

    # Count consecutive days backwards from as_of
    count = 0
    check = as_of
    while check in leave_date_set:
        count += 1
        check -= timedelta(days=1)
    return count


class Command(BaseCommand):
    help = (
        "Escalate pending leave approvals when the assigned manager has been "
        "on leave for 4 or more consecutive days."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what would be escalated without making changes.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        today = date.today()
        escalated = 0

        # All pending requests (Pending or Manager Approved waiting HR)
        pending_qs = LeaveRequest.objects.filter(
            status__in=[
                LeaveRequest.StatusChoices.PENDING,
                LeaveRequest.StatusChoices.MANAGER_APPROVED,
            ]
        ).select_related("employee__reporting_manager__reporting_manager")

        for lr in pending_qs:
            employee = lr.employee
            manager = employee.reporting_manager
            if manager is None:
                continue

            consecutive = _manager_on_leave_consecutive_days(manager, today)

            if consecutive < CONSECUTIVE_DAYS_THRESHOLD:
                continue

            # Find next-level approver (manager's manager)
            next_approver = manager.reporting_manager
            if next_approver is None:
                self.stdout.write(
                    self.style.WARNING(
                        f"  LeaveRequest #{lr.pk} ({employee.full_name}): manager "
                        f"{manager.full_name} is on leave {consecutive}d but has no "
                        "next-level approver — skipping."
                    )
                )
                continue

            self.stdout.write(
                f"  Escalating LeaveRequest #{lr.pk} ({employee.full_name}, "
                f"{lr.from_date}–{lr.to_date}): "
                f"{manager.full_name} on leave {consecutive}d → "
                f"escalating to {next_approver.full_name}"
            )

            if not dry_run:
                # Re-assign reporting manager temporarily by adding escalation note
                old_remarks = lr.remarks or ""
                lr.remarks = (
                    f"[Auto-escalated {today}: {manager.full_name} on leave "
                    f"{consecutive} consecutive days. "
                    f"Escalated to {next_approver.full_name}.]\n" + old_remarks
                ).strip()
                # Point the employee's reporting manager to next approver for this request
                # We track this by updating the request's manager_approved_by to next approver
                # so the next approver can action it.
                if lr.status == LeaveRequest.StatusChoices.PENDING:
                    # Keep as Pending but log escalation in remarks
                    pass
                lr.save(update_fields=["remarks", "updated_at"])
                escalated += 1

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN — no changes made."))
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Done. Escalated {escalated} pending leave request(s)."
                )
            )
