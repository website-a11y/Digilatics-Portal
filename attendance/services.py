"""
Attendance ↔ Leave synchronisation service.

Rule summary
────────────
• When a LeaveRequest is APPROVED
    → create/update an AttendanceRecord (ON_LEAVE_PAID or ON_LEAVE_UNPAID)
      for every working day (Mon–Fri, non-public-holiday) in the date range.
    → any previously-linked records outside the new date range are cleaned up.

• When a LeaveRequest moves away from APPROVED (REJECTED / CANCELLED / PENDING)
    → future records linked to it are deleted (they never happened).
    → past records linked to it are set to ABSENT and unlinked, preserving the
      fact that the employee had no approved leave that day.

• Public holidays and weekends are never overwritten — they keep their own status.

All functions are idempotent: safe to call multiple times.
"""
from __future__ import annotations

from datetime import date, timedelta
from datetime import time as time_type

from django.utils import timezone

from .models import AttendanceRecord, AttendancePolicy, PublicHoliday


def _time_to_minutes(t: time_type) -> int:
    return t.hour * 60 + t.minute


def compute_attendance_flags(employee, check_in: time_type | None, check_out: time_type | None) -> dict:
    """
    Return {'is_late': bool, 'is_early_checkout': bool} based on the employee's
    scheduled times and the global AttendancePolicy buffer settings.

    Handles overnight shifts (e.g. 4 PM – 1 AM) by normalising times to
    a 48-hour window so cross-midnight comparisons stay correct.
    """
    policy = AttendancePolicy.objects.first()
    checkin_buffer = policy.checkin_buffer_minutes if policy else 0
    checkout_buffer = policy.checkout_buffer_minutes if policy else 0

    scheduled_in = employee.scheduled_checkin
    scheduled_out = employee.scheduled_checkout

    is_late = False
    is_early_checkout = False

    if scheduled_in and check_in:
        scheduled_in_mins = _time_to_minutes(scheduled_in)
        checkin_mins = _time_to_minutes(check_in)
        
        # Overnight shift: if check_in is before scheduled_in, it might be from the next day
        if scheduled_out and _time_to_minutes(scheduled_out) < scheduled_in_mins:
            if checkin_mins < scheduled_in_mins:
                checkin_mins += 24 * 60
        
        # Employee is late if they punched in more than buffer minutes after scheduled time.
        is_late = checkin_mins > scheduled_in_mins + checkin_buffer

    if scheduled_out and check_out:
        scheduled_out_mins = _time_to_minutes(scheduled_out)
        checkout_mins = _time_to_minutes(check_out)

        if scheduled_in:
            scheduled_in_mins = _time_to_minutes(scheduled_in)
            # Overnight shift: checkout time is on the next calendar day.
            if scheduled_out_mins < scheduled_in_mins:
                scheduled_out_mins += 24 * 60
                # If actual checkout is also past midnight (i.e. < scheduled_in time),
                # shift it forward by 24 h for an apples-to-apples comparison.
                if checkout_mins < scheduled_in_mins:
                    checkout_mins += 24 * 60

        # Employee left early if they punched out before (scheduled_out − buffer).
        is_early_checkout = checkout_mins < scheduled_out_mins - checkout_buffer

    return {"is_late": is_late, "is_early_checkout": is_early_checkout}


def _leave_attendance_status(leave_type) -> str:
    """Map a LeaveType to the matching AttendanceRecord status string."""
    if leave_type.is_paid:
        return AttendanceRecord.StatusChoices.ON_LEAVE_PAID
    return AttendanceRecord.StatusChoices.ON_LEAVE_UNPAID


def _working_dates_in_range(from_date: date, to_date: date) -> list[date]:
    """Return Mon–Fri dates between from_date and to_date (inclusive)."""
    delta = (to_date - from_date).days
    return [
        from_date + timedelta(days=i)
        for i in range(delta + 1)
        if (from_date + timedelta(days=i)).weekday() < 5
    ]


def sync_leave_request_to_attendance(leave_request) -> None:
    """
    Main sync entry-point.  Call this whenever a LeaveRequest is saved.
    Imports are deferred so this module can be imported safely at startup.
    """
    from leaves.models import LeaveRequest  # avoid circular at module level

    employee = leave_request.employee
    today = timezone.localdate()
    working_dates = _working_dates_in_range(
        leave_request.from_date, leave_request.to_date
    )

    if leave_request.status == LeaveRequest.StatusChoices.APPROVED:
        # ── Fetch public holidays once for the whole range ──────────────
        if working_dates:
            holiday_set: set[date] = PublicHoliday.dates_in_range(
                min(working_dates), max(working_dates)
            )
        else:
            holiday_set: set[date] = set()

        att_status = _leave_attendance_status(leave_request.leave_type)
        note = f"On leave: {leave_request.leave_type.name}"

        # ── Remove stale linked records outside the current date range ──
        AttendanceRecord.objects.filter(
            employee=employee,
            leave_request=leave_request,
        ).exclude(date__in=working_dates).delete()

        # ── Create / update one record per eligible working day ─────────
        for day in working_dates:
            if day in holiday_set:
                # Public holidays keep their own status — don't overwrite.
                continue

            AttendanceRecord.objects.update_or_create(
                employee=employee,
                date=day,
                defaults={
                    "status": att_status,
                    "leave_request": leave_request,
                    "notes": note,
                },
            )

    else:
        # ── Leave not (or no longer) approved ───────────────────────────
        linked_qs = AttendanceRecord.objects.filter(
            employee=employee,
            leave_request=leave_request,
        )

        # Future records: delete — the employee hasn't been absent yet.
        linked_qs.filter(date__gt=today).delete()

        # Past / today records: preserve history as ABSENT and unlink.
        linked_qs.filter(date__lte=today).update(
            status=AttendanceRecord.StatusChoices.ABSENT,
            leave_request=None,
            notes=(
                f"Leave #{leave_request.pk} ({leave_request.leave_type.name}) "
                f"was {leave_request.status.lower()}."
            ),
        )


def resync_all_approved_leaves() -> int:
    """
    Re-run sync for every currently-APPROVED LeaveRequest.
    Useful as a management utility or admin action after bulk data changes.
    Returns the number of leave requests processed.
    """
    from leaves.models import LeaveRequest

    approved = LeaveRequest.objects.filter(
        status=LeaveRequest.StatusChoices.APPROVED
    ).select_related("employee", "leave_type")

    count = 0
    for lr in approved:
        sync_leave_request_to_attendance(lr)
        count += 1
    return count
