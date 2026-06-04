from datetime import date, timedelta
import calendar

from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from .models import EmployeeProfile
from attendance.models import AttendanceRecord, PublicHoliday


def _month_bounds(year, month):
    _, last = calendar.monthrange(year, month)
    return date(year, month, 1), date(year, month, last)


@login_required
def employee_profile(request, pk):
    emp = get_object_or_404(EmployeeProfile, pk=pk)

    today = timezone.localdate()
    year, month = today.year, today.month
    start, end = _month_bounds(year, month)

    holidays = set(
        PublicHoliday.objects.filter(date__range=(start, end), is_active=True)
        .values_list("date", flat=True)
    )

    records = AttendanceRecord.objects.filter(employee=emp, date__range=(start, end))
    record_map = {rec.date: rec for rec in records}

    present = absent = leave_paid = leave_unpaid = hourly_leave = half_day = holiday = not_recorded = late = early_checkout = 0
    working_days = 0

    current_days = [start + timedelta(days=i) for i in range((today - start).days + 1)]
    for day in current_days:
        if day.weekday() >= 5:
            continue
        working_days += 1
        record = record_map.get(day)
        if day in holidays and not record:
            holiday += 1
        elif record:
            status = record.status
            if status == AttendanceRecord.StatusChoices.PRESENT:
                present += 1
                if record.is_late:
                    late += 1
                if record.is_early_checkout:
                    early_checkout += 1
            elif status == AttendanceRecord.StatusChoices.ABSENT:
                absent += 1
            elif status == AttendanceRecord.StatusChoices.ON_LEAVE_PAID:
                leave_paid += 1
            elif status == AttendanceRecord.StatusChoices.ON_LEAVE_UNPAID:
                leave_unpaid += 1
            elif status == AttendanceRecord.StatusChoices.ON_HOURLY_LEAVE:
                hourly_leave += 1
                if record.is_late:
                    late += 1
                if record.is_early_checkout:
                    early_checkout += 1
            elif status == AttendanceRecord.StatusChoices.HALF_DAY:
                half_day += 1
            elif status == AttendanceRecord.StatusChoices.PUBLIC_HOLIDAY:
                holiday += 1
        else:
            not_recorded += 1

    attendance_pct = round(present / working_days * 100) if working_days else 0

    return render(request, "accounts/employee_profile.html", {
        "emp": emp,
        "attendance_month_label": start.strftime("%B %Y"),
        "attendance_year": year,
        "attendance_month": month,
        "attendance_present": present,
        "attendance_absent": absent,
        "attendance_leave_paid": leave_paid,
        "attendance_leave_unpaid": leave_unpaid,
        "attendance_hourly_leave": hourly_leave,
        "attendance_half_day": half_day,
        "attendance_holiday": holiday,
        "attendance_not_recorded": not_recorded,
        "attendance_late": late,
        "attendance_early_checkout": early_checkout,
        "attendance_working_days": working_days,
        "attendance_pct": attendance_pct,
    })


@login_required
def employee_directory(request):
    search = request.GET.get("q", "").strip()
    status_filter = request.GET.get("status", "")
    active_tab = request.GET.get("tab", "employees")

    employees = EmployeeProfile.objects.all()

    if search:
        employees = employees.filter(
            Q(full_name__icontains=search)
            | Q(designation__icontains=search)
            | Q(department__icontains=search)
            | Q(employee_code__icontains=search)
            | Q(official_email__icontains=search)
        ).distinct()

    if status_filter:
        employees = employees.filter(employment_status=status_filter)

    total_count = EmployeeProfile.objects.count()
    active_count = EmployeeProfile.objects.filter(employment_status="Active").count()
    on_leave_count = EmployeeProfile.objects.filter(employment_status="On Leave").count()

    context = {
        "employees": employees,
        "total_count": total_count,
        "active_count": active_count,
        "on_leave_count": on_leave_count,
        "search": search,
        "status_filter": status_filter,
        "active_tab": active_tab,
    }
    return render(request, "accounts/employee_directory.html", context)
