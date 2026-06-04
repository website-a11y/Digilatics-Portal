"""
Patches django.contrib.admin.site to inject dashboard KPI context
into the admin index page. Import this in any AppConfig.ready() or
the project __init__.py — it is idempotent.
"""
from datetime import date as _date

from django.contrib import admin


def _patched_index(self, request, extra_context=None):
    extra_context = extra_context or {}

    # Employee count
    try:
        from accounts.models import EmployeeProfile
        extra_context.setdefault("employee_count", EmployeeProfile.objects.count())
    except Exception:
        extra_context.setdefault("employee_count", "—")

    # Attendance today
    try:
        from attendance.models import AttendanceRecord
        extra_context.setdefault(
            "attendance_today",
            AttendanceRecord.objects.filter(date=_date.today()).count(),
        )
    except Exception:
        extra_context.setdefault("attendance_today", "—")

    # Pending leaves
    try:
        from leaves.models import LeaveRequest
        extra_context.setdefault(
            "leave_pending",
            LeaveRequest.objects.filter(status="Pending").count(),
        )
    except Exception:
        extra_context.setdefault("leave_pending", "—")

    # Payroll runs
    try:
        from salary.models import PayrollRun
        extra_context.setdefault("payroll_runs", PayrollRun.objects.count())
    except Exception:
        extra_context.setdefault("payroll_runs", "—")

    # Active salary setups
    try:
        from salary.models import SalarySetup
        extra_context.setdefault(
            "salary_setups",
            SalarySetup.objects.filter(is_active=True).count(),
        )
    except Exception:
        extra_context.setdefault("salary_setups", "—")

    # Call the original (unpatched) method
    return _patched_index._original(request, extra_context=extra_context)


def patch_admin_index():
    """Call once from an AppConfig.ready() to inject dashboard KPIs."""
    if getattr(admin.site.index, "_di_patched", False):
        return  # already done

    import types
    original = admin.site.index

    def new_index(request, extra_context=None):
        return _patched_index(admin.site, request, extra_context)

    _patched_index._original = original
    new_index._di_patched = True
    admin.site.index = new_index
