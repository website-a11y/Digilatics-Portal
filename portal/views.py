import calendar
from decimal import Decimal
from datetime import date, datetime, timedelta
from django.db.models import Count, Case, When, IntegerField, Q

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, get_user_model
from django.contrib.auth.decorators import login_required
from django.conf import settings
from django.core.management import call_command, CommandError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from accounts.models import EmployeeProfile
from io import StringIO

User = get_user_model()
from attendance.models import AttendanceRecord, PublicHoliday
from attendance.services import compute_attendance_flags
from leaves.models import LeaveAllocation, LeaveRequest, LeaveType
from salary.models import Payslip


def _get_employee(request):
    try:
        return request.user.employee_profile
    except (AttributeError, EmployeeProfile.DoesNotExist):
        return None


def _number_to_words(value: int) -> str:
    if value == 0:
        return "Zero"
    units = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen"]
    tens = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]
    scales = ["", "Thousand", "Million", "Billion"]

    def three_digit_words(num: int) -> str:
        words = []
        hundred = num // 100
        remainder = num % 100
        if hundred:
            words.append(units[hundred])
            words.append("Hundred")
        if remainder:
            if remainder < 20:
                words.append(units[remainder])
            else:
                ten = remainder // 10
                unit = remainder % 10
                words.append(tens[ten])
                if unit:
                    words.append(units[unit])
        return " ".join(words)

    chunks = []
    scale_index = 0
    while value > 0:
        chunk = value % 1000
        if chunk:
            chunk_words = three_digit_words(chunk)
            scale_name = scales[scale_index]
            if scale_name:
                chunks.append(f"{chunk_words} {scale_name}".strip())
            else:
                chunks.append(chunk_words)
        value //= 1000
        scale_index += 1

    return ", ".join(reversed(chunks)).replace(" ,", ",")


def _month_stats(emp, year, month):
    _, last_day = calendar.monthrange(year, month)
    start = date(year, month, 1)
    end = date(year, month, last_day)
    today = timezone.localdate()

    holidays = PublicHoliday.dates_in_range(start, end)
    from attendance.models import CompanyWFHDay
    company_wfh_dates = CompanyWFHDay.dates_in_range(start, end)
    records = AttendanceRecord.objects.filter(employee=emp, date__range=(start, end))
    record_map = {r.date: r for r in records}

    stats = dict(present=0, absent=0, late=0, leave=0, wfh=0, holiday=0, half_day=0, not_recorded=0, working_days=0)
    days_up_to = min(today, end)
    if days_up_to < start:
        return stats, record_map

    for i in range((days_up_to - start).days + 1):
        day = start + timedelta(days=i)
        if day.weekday() >= 5:
            continue
        stats["working_days"] += 1
        rec = record_map.get(day)
        if day in holidays and not rec:
            stats["holiday"] += 1
        elif rec:
            s = rec.status
            if s == AttendanceRecord.StatusChoices.PRESENT:
                stats["present"] += 1
                if rec.is_late:
                    stats["late"] += 1
            elif s == AttendanceRecord.StatusChoices.ABSENT:
                stats["absent"] += 1
            elif s in (
                AttendanceRecord.StatusChoices.ON_LEAVE_PAID,
                AttendanceRecord.StatusChoices.ON_LEAVE_UNPAID,
                AttendanceRecord.StatusChoices.ON_HOURLY_LEAVE,
            ):
                stats["leave"] += 1
            elif s == AttendanceRecord.StatusChoices.WORK_FROM_HOME:
                stats["wfh"] += 1
            elif s == AttendanceRecord.StatusChoices.PUBLIC_HOLIDAY:
                stats["holiday"] += 1
            elif s == AttendanceRecord.StatusChoices.HALF_DAY:
                stats["half_day"] += 1
        elif day in company_wfh_dates:
            stats["wfh"] += 1
        else:
            stats["not_recorded"] += 1

    return stats, record_map


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Auth
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def portal_login(request):
    if request.user.is_authenticated:
        u = request.user
        ep = getattr(u, "employee_profile", None)
        if u.is_superuser or (ep and ep.role == EmployeeProfile.RoleChoices.SUPER_ADMIN):
            return redirect("portal:hr_dashboard")
        if ep and ep.role in [EmployeeProfile.RoleChoices.MANAGER, EmployeeProfile.RoleChoices.APPROVER]:
            return redirect("portal:manager_dashboard")
        return redirect("portal:dashboard")

    error = None
    if request.method == "POST":
        identifier = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")

        # Allow login by email: look up the username from official_email or auth email
        username = identifier
        if "@" in identifier:
            db_user = (
                User.objects.filter(email__iexact=identifier).first()
                or User.objects.filter(
                    employee_profile__official_email__iexact=identifier
                ).first()
            )
            if db_user:
                username = db_user.username

        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            next_url = request.GET.get("next", "")
            if next_url:
                return redirect(next_url)
            # Role-based redirect
            emp_profile = getattr(user, "employee_profile", None)
            # HR-level: superuser or Super Admin role â†’ HR panel
            if user.is_superuser or (emp_profile and emp_profile.role == EmployeeProfile.RoleChoices.SUPER_ADMIN):
                return redirect("portal:hr_dashboard")
            # No employee profile (plain staff) â†’ Django admin
            if not emp_profile:
                return redirect("/admin/")
            # Manager / Approver â†’ manager dashboard
            if emp_profile.role in [EmployeeProfile.RoleChoices.MANAGER, EmployeeProfile.RoleChoices.APPROVER]:
                return redirect("portal:manager_dashboard")
            return redirect("portal:dashboard")
        error = "Invalid email/username or password."

    return render(request, "portal/login.html", {"error": error})


def portal_logout(request):
    logout(request)
    return redirect("portal:login")


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Dashboard
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@login_required(login_url="/portal/login/")
def portal_dashboard(request):
    emp = _get_employee(request)
    if emp is None:
        return redirect("/admin/")

    today = timezone.localdate()
    year, month = today.year, today.month

    stats, record_map = _month_stats(emp, year, month)
    today_record = record_map.get(today)

    att_pct = round(stats["present"] / stats["working_days"] * 100) if stats["working_days"] else 0

    leave_allocations = (
        LeaveAllocation.objects.filter(employee=emp, year=year)
        .select_related("leave_type")
        .order_by("leave_type__name")
    )

    recent_leaves = (
        LeaveRequest.objects.filter(employee=emp)
        .select_related("leave_type")
        .order_by("-created_at")[:5]
    )

    latest_payslip = (
        Payslip.objects.filter(employee=emp)
        .select_related("payroll_run")
        .order_by("-payroll_run__year", "-payroll_run__month")
        .first()
    )

    return render(request, "portal/dashboard.html", {
        "emp": emp,
        "today": today,
        "today_record": today_record,
        "att_pct": att_pct,
        "stats": stats,
        "leave_allocations": leave_allocations,
        "recent_leaves": recent_leaves,
        "latest_payslip": latest_payslip,
        "month_label": today.strftime("%B %Y"),
    })


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Attendance
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@login_required(login_url="/portal/login/")
def portal_attendance(request):
    emp = _get_employee(request)
    if emp is None:
        return redirect("/admin/")

    today = timezone.localdate()
    try:
        year = int(request.GET.get("year", today.year))
        month = int(request.GET.get("month", today.month))
    except ValueError:
        year, month = today.year, today.month

    month = max(1, min(12, month))

    prev_month = month - 1 or 12
    prev_year = year - 1 if month == 1 else year
    next_month = month % 12 + 1
    next_year = year + 1 if month == 12 else year

    _, last_day = calendar.monthrange(year, month)
    start = date(year, month, 1)
    end = date(year, month, last_day)

    holidays = PublicHoliday.dates_in_range(start, end)
    from attendance.models import CompanyWFHDay
    company_wfh_dates = CompanyWFHDay.dates_in_range(start, end)
    records = AttendanceRecord.objects.filter(employee=emp, date__range=(start, end))
    record_map = {r.date: r for r in records}

    cells = []
    stats = dict(present=0, absent=0, late=0, leave=0, wfh=0, holiday=0, half_day=0, not_recorded=0)

    for i in range(last_day):
        day = start + timedelta(days=i)
        is_weekend = day.weekday() >= 5
        is_today = day == today
        is_future = day > today
        rec = record_map.get(day)

        if is_weekend:
            status = "weekend"
        elif day in holidays and not rec:
            status = "holiday"
            stats["holiday"] += 1
        elif rec:
            s = rec.status
            if s == AttendanceRecord.StatusChoices.PRESENT:
                status = "present"
                stats["present"] += 1
                if rec.is_late:
                    stats["late"] += 1
            elif s == AttendanceRecord.StatusChoices.ABSENT:
                status = "absent"
                stats["absent"] += 1
            elif s in (
                AttendanceRecord.StatusChoices.ON_LEAVE_PAID,
                AttendanceRecord.StatusChoices.ON_LEAVE_UNPAID,
                AttendanceRecord.StatusChoices.ON_HOURLY_LEAVE,
            ):
                status = "leave"
                stats["leave"] += 1
            elif s == AttendanceRecord.StatusChoices.WORK_FROM_HOME:
                status = "wfh"
                stats["wfh"] += 1
            elif s == AttendanceRecord.StatusChoices.PUBLIC_HOLIDAY:
                status = "holiday"
                stats["holiday"] += 1
            elif s == AttendanceRecord.StatusChoices.HALF_DAY:
                status = "half_day"
                stats["half_day"] += 1
            else:
                status = s
        elif day in company_wfh_dates:
            status = "wfh"
            stats["wfh"] += 1
        elif is_future:
            status = "future"
        else:
            status = "not_recorded"
            stats["not_recorded"] += 1

        cells.append({
            "day": day,
            "num": day.day,
            "name": day.strftime("%a"),
            "status": status,
            "record": rec,
            "is_weekend": is_weekend,
            "is_today": is_today,
            "is_future": is_future,
        })

    return render(request, "portal/attendance.html", {
        "emp": emp,
        "cells": cells,
        "stats": stats,
        "year": year,
        "month": month,
        "month_label": date(year, month, 1).strftime("%B %Y"),
        "prev_year": prev_year,
        "prev_month": prev_month,
        "next_year": next_year,
        "next_month": next_month,
        "today": today,
        "first_weekday": start.weekday(),
    })


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Leave
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@login_required(login_url="/portal/login/")
def portal_leave(request):
    emp = _get_employee(request)
    if emp is None:
        return redirect("/admin/")

    today = timezone.localdate()
    year = today.year

    if request.method == "POST":
        leave_type_id = request.POST.get("leave_type")
        from_date_str = request.POST.get("from_date")
        to_date_str = request.POST.get("to_date")
        reason = request.POST.get("reason", "").strip()

        try:
            leave_type = LeaveType.objects.get(pk=leave_type_id, is_active=True)
            from_date = datetime.strptime(from_date_str, "%Y-%m-%d").date()
            to_date = datetime.strptime(to_date_str, "%Y-%m-%d").date()

            if to_date < from_date:
                messages.error(request, "End date cannot be before start date.")
            elif from_date < today:
                messages.error(request, "Cannot apply for leave on past dates.")
            else:
                num_days = sum(
                    1 for i in range((to_date - from_date).days + 1)
                    if (from_date + timedelta(days=i)).weekday() < 5
                )
                if num_days == 0:
                    messages.error(request, "Selected dates fall on weekends only.")
                else:
                    if leave_type.is_wfh:
                        # WFH: check monthly balance instead of annual allocation
                        from leaves.models import WFHBalance
                        from decimal import Decimal as _D
                        wfh_bal, _ = WFHBalance.objects.get_or_create(employee=emp)
                        wfh_bal.accrue()
                        if _D(str(num_days)) > wfh_bal.available_days:
                            avail = wfh_bal.available_days
                            avail_str = str(avail).rstrip("0").rstrip(".")
                            messages.error(request, f"Insufficient WFH balance. Available: {avail_str} day(s).")
                        else:
                            lr = LeaveRequest(
                                employee=emp,
                                leave_type=leave_type,
                                from_date=from_date,
                                to_date=to_date,
                                number_of_days=num_days,
                                reason=reason,
                                created_by=emp,
                            )
                            if leave_type.requires_attachment and "attachment" in request.FILES:
                                lr.attachment = request.FILES["attachment"]
                            lr.save()
                            messages.success(request, "WFH request submitted successfully.")
                            return redirect("portal:leave")
                    else:
                        allocation = LeaveAllocation.objects.filter(
                            employee=emp, leave_type=leave_type, year=from_date.year
                        ).first()

                        if not allocation:
                            messages.error(request, f"No leave allocation found for {leave_type.name}.")
                        elif num_days > float(allocation.remaining_days):
                            messages.error(
                                request,
                                f"Insufficient balance. Available: {allocation.remaining_days} days."
                            )
                        else:
                            lr = LeaveRequest(
                                employee=emp,
                                leave_type=leave_type,
                                allocation=allocation,
                                from_date=from_date,
                                to_date=to_date,
                                number_of_days=num_days,
                                reason=reason,
                                created_by=emp,
                            )
                            if leave_type.requires_attachment and "attachment" in request.FILES:
                                lr.attachment = request.FILES["attachment"]
                            lr.save()
                            messages.success(request, "Leave request submitted successfully.")
                            return redirect("portal:leave")

        except LeaveType.DoesNotExist:
            messages.error(request, "Invalid leave type selected.")
        except ValueError:
            messages.error(request, "Invalid date format.")

    allocations = (
        LeaveAllocation.objects.filter(employee=emp, year=year)
        .select_related("leave_type")
        .order_by("leave_type__name")
    )
    leave_types = LeaveType.objects.filter(is_active=True).order_by("name")
    leave_requests = (
        LeaveRequest.objects.filter(employee=emp)
        .select_related("leave_type")
        .order_by("-from_date")[:30]
    )

    # WFH balance (lazy accrual)
    from leaves.models import WFHBalance
    wfh_balance_obj = None
    wfh_leave_type = LeaveType.objects.filter(is_wfh=True, is_active=True).first()
    if wfh_leave_type:
        wfh_balance_obj, _ = WFHBalance.objects.get_or_create(employee=emp)
        wfh_balance_obj.accrue()

    # Company WFH days (upcoming)
    from attendance.models import CompanyWFHDay
    company_wfh_days = CompanyWFHDay.objects.filter(is_active=True, start_date__gte=today).order_by("start_date")[:5]

    from leaves.models import WFHPolicy, ShortLeavePolicy, ShortLeaveRequest as SLR
    sl_policy = ShortLeavePolicy.get()
    # Short leave: count used this month
    sl_used_this_month = SLR.objects.filter(
        employee=emp,
        date__year=today.year,
        date__month=today.month,
        status__in=[SLR.StatusChoices.PENDING, SLR.StatusChoices.MANAGER_APPROVED, SLR.StatusChoices.APPROVED],
    ).count()
    sl_remaining = max(0, sl_policy.max_per_month - sl_used_this_month)
    sl_recent = SLR.objects.filter(employee=emp).order_by("-date")[:10]

    return render(request, "portal/leave.html", {
        "emp": emp,
        "allocations": allocations,
        "leave_types": leave_types,
        "leave_requests": leave_requests,
        "today": today,
        "today_str": today.isoformat(),
        "wfh_balance": wfh_balance_obj,
        "wfh_leave_type": wfh_leave_type,
        "wfh_policy": WFHPolicy.get(),
        "company_wfh_days": company_wfh_days,
        "sl_policy": sl_policy,
        "sl_used": sl_used_this_month,
        "sl_remaining": sl_remaining,
        "sl_recent": sl_recent,
    })


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Short Leave
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@login_required(login_url="/portal/login/")
def portal_short_leave_apply(request):
    """Employee applies for a short leave."""
    from leaves.models import ShortLeavePolicy, ShortLeaveRequest as SLR
    from attendance.models import AttendanceRecord
    from datetime import datetime as _dt, timedelta

    emp = _get_employee(request)
    if emp is None:
        return redirect("/admin/")

    today = timezone.localdate()
    policy = ShortLeavePolicy.get()
    errors = {}

    if not policy.is_enabled:
        messages.error(request, "Short leave is currently disabled by the company.")
        return redirect("portal:leave")

    if request.method == "POST":
        p = request.POST
        try:
            date_str = p.get("date", "").strip()
            period = p.get("period", "").strip()
            from_time_str = p.get("from_time", "").strip()
            to_time_str = p.get("to_time", "").strip()
            reason = p.get("reason", "").strip()

            if not date_str:
                raise ValueError("Date is required.")
            req_date = _dt.strptime(date_str, "%Y-%m-%d").date()

            if period not in (SLR.PeriodChoices.MORNING, SLR.PeriodChoices.AFTERNOON):
                raise ValueError("Please select Morning or Afternoon.")

            if not from_time_str or not to_time_str:
                raise ValueError("From time and to time are required.")

            from_time = _dt.strptime(from_time_str, "%H:%M").time()
            to_time   = _dt.strptime(to_time_str,   "%H:%M").time()

            if to_time <= from_time:
                raise ValueError("To time must be after from time.")

            # Duration checks
            from datetime import datetime as _dt2, date as _d2
            _start_dt = _dt2.combine(_d2.today(), from_time)
            _end_dt   = _dt2.combine(_d2.today(), to_time)
            _duration_hours = (_end_dt - _start_dt).total_seconds() / 3600
            if _duration_hours > 4:
                raise ValueError(
                    "HALF_DAY_ESCALATION: This request exceeds the 4-hour limit and will be "
                    "calculated as a half-day leave. Please resubmit your application using "
                    "the Half-Day Leave option."
                )
            if _duration_hours > 2:
                raise ValueError(
                    f"Short leave cannot exceed 2 hours. Your selected duration is "
                    f"{int(_duration_hours)}h {int((_duration_hours % 1) * 60)}m. "
                    "Please adjust your times."
                )

            # Check monthly quota
            used = SLR.objects.filter(
                employee=emp, date__year=req_date.year, date__month=req_date.month,
                status__in=[SLR.StatusChoices.PENDING, SLR.StatusChoices.MANAGER_APPROVED, SLR.StatusChoices.APPROVED],
            ).count()
            if used >= policy.max_per_month:
                raise ValueError(
                    f"You have used all {policy.max_per_month} short leave(s) for {req_date.strftime('%B %Y')}."
                )

            # For afternoon: check actual hours worked from attendance
            if period == SLR.PeriodChoices.AFTERNOON:
                rec = AttendanceRecord.objects.filter(employee=emp, date=req_date).first()
                if not rec or not rec.check_in:
                    raise ValueError(
                        "No check-in record found for this date. "
                        "You must be checked in before applying for an afternoon short leave."
                    )
                check_in_dt = _dt.combine(req_date, rec.check_in)
                from_dt = _dt.combine(req_date, from_time)
                hours_worked = (from_dt - check_in_dt).total_seconds() / 3600
                min_h = float(policy.min_hours_before_afternoon)
                if hours_worked < min_h:
                    worked_str = f"{int(hours_worked)}h {int((hours_worked % 1)*60)}m"
                    raise ValueError(
                        f"You need to work at least {policy.min_hours_before_afternoon} hours before applying. "
                        f"You have worked {worked_str} so far."
                    )

            # No duplicate on same date + period
            if SLR.objects.filter(
                employee=emp, date=req_date, period=period,
                status__in=[SLR.StatusChoices.PENDING, SLR.StatusChoices.MANAGER_APPROVED, SLR.StatusChoices.APPROVED],
            ).exists():
                raise ValueError(f"You already have a {period.lower()} short leave request for {req_date}.")

            SLR.objects.create(
                employee=emp, date=req_date, period=period,
                from_time=from_time, to_time=to_time,
                reason=reason, status=SLR.StatusChoices.PENDING,
            )
            messages.success(request, f"{period} short leave applied for {req_date.strftime('%d %b %Y')}.")
            return redirect("portal:leave")

        except ValueError as e:
            errors["general"] = str(e)

    # Auto-fill times from shift
    shift = emp.shift_master
    shift_start = shift.start_time if shift else None
    shift_end   = shift.end_time   if shift else None
    shift_mid   = None
    if shift_start and shift_end:
        start_mins = shift_start.hour * 60 + shift_start.minute
        end_mins   = shift_end.hour   * 60 + shift_end.minute
        if end_mins < start_mins:
            end_mins += 1440  # overnight
        mid_mins = (start_mins + end_mins) // 2
        mid_mins = mid_mins % 1440
        shift_mid = f"{mid_mins // 60:02d}:{mid_mins % 60:02d}"

    # Monthly stats
    used = SLR.objects.filter(
        employee=emp, date__year=today.year, date__month=today.month,
        status__in=[SLR.StatusChoices.PENDING, SLR.StatusChoices.MANAGER_APPROVED, SLR.StatusChoices.APPROVED],
    ).count()

    return render(request, "portal/short_leave_apply.html", {
        "emp": emp, "today": today, "today_str": today.isoformat(),
        "policy": policy, "errors": errors,
        "shift_start": shift_start.strftime("%H:%M") if shift_start else "",
        "shift_end":   shift_end.strftime("%H:%M")   if shift_end   else "",
        "shift_mid":   shift_mid or "",
        "sl_used": used,
        "sl_remaining": max(0, policy.max_per_month - used),
    })


@login_required(login_url="/portal/login/")
def portal_short_leave_cancel(request, pk):
    from leaves.models import ShortLeaveRequest as SLR
    emp = _get_employee(request)
    if emp is None:
        return redirect("/admin/")
    sl = get_object_or_404(SLR, pk=pk, employee=emp)
    if sl.status in (SLR.StatusChoices.PENDING, SLR.StatusChoices.MANAGER_APPROVED):
        sl.status = SLR.StatusChoices.CANCELLED
        sl.save(update_fields=["status", "updated_at"])
        messages.success(request, "Short leave request cancelled.")
    else:
        messages.error(request, "Cannot cancel a request that is already approved or rejected.")
    return redirect("portal:leave")


@login_required(login_url="/portal/login/")
def portal_manager_short_leave_action(request, pk):
    """Manager approves / rejects a short leave."""
    from leaves.models import ShortLeaveRequest as SLR
    emp = _get_employee(request)
    if emp is None:
        return redirect("/admin/")
    if emp.role not in _MANAGER_ROLES and not request.user.is_superuser:
        return redirect("portal:manager_dashboard")

    if request.method != "POST":
        return redirect("portal:manager_dashboard")

    sl = get_object_or_404(SLR, pk=pk, employee__reporting_manager=emp, status=SLR.StatusChoices.PENDING)
    action  = request.POST.get("action")
    remarks = request.POST.get("remarks", "").strip()
    if action == "approve":
        sl.status = SLR.StatusChoices.MANAGER_APPROVED
        sl.manager_approved_by = emp
        if remarks: sl.remarks = remarks
        sl.save()
        messages.success(request, f"Short leave approved for {sl.employee.full_name}.")
    elif action == "reject":
        sl.status = SLR.StatusChoices.REJECTED
        if remarks: sl.remarks = remarks
        sl.save()
        messages.warning(request, f"Short leave rejected for {sl.employee.full_name}.")
    return redirect("portal:manager_dashboard")


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Profile
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@login_required(login_url="/portal/login/")
def portal_profile(request):
    emp = _get_employee(request)
    if emp is None:
        return redirect("/admin/")
    return render(request, "portal/profile.html", {"emp": emp})


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Payslips
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@login_required(login_url="/portal/login/")
def portal_payslips(request):
    emp = _get_employee(request)
    if emp is None:
        return redirect("/admin/")

    payslips = (
        Payslip.objects.filter(employee=emp)
        .select_related("payroll_run", "salary_revision")
        .order_by("-payroll_run__year", "-payroll_run__month")
    )

    payslip_rows = []
    for ps in payslips:
        source = ps.salary_revision or emp
        base_salary = getattr(source, "basic_salary", 0) or 0
        total_allowance = sum(
            getattr(source, field, 0) or 0
            for field in (
                "house_rent_allowance",
                "conveyance_allowance",
                "medical_allowance",
                "other_allowance",
            )
        )
        pay_date = ps.paid_at or ps.created_at or ps.payroll_run.period_end
        payslip_rows.append({
            "pk": ps.pk,
            "period": f"{ps.payroll_run.period_start.strftime('%d/%m/%Y')} - {ps.payroll_run.period_end.strftime('%d/%m/%Y')}",
            "pay_date": pay_date,
            "base_salary": base_salary,
            "allowance": total_allowance,
            "gross_salary": ps.gross_salary,
            "deduction": ps.total_deductions,
            "tax": ps.income_tax,
            "net_salary": ps.net_salary,
            "status": ps.status,
            "is_paid": ps.is_paid,
            "paid_at": ps.paid_at,
            "detail_url": reverse("portal:payslip_detail", args=[ps.pk]),
        })

    return render(request, "portal/payslips.html", {
        "emp": emp,
        "payslips": payslips,
        "payslip_rows": payslip_rows,
    })


@login_required(login_url="/portal/login/")
def portal_payslip_detail(request, pk):
    emp = _get_employee(request)
    if emp is None:
        return redirect("/admin/")

    payslip = get_object_or_404(Payslip, pk=pk, employee=emp)
    period_days = (
        payslip.payroll_run.period_end - payslip.payroll_run.period_start
    ).days + 1
    net_salary_value = int(payslip.net_salary or 0)
    net_salary_words = _number_to_words(net_salary_value)

    # If requested as a modal partial, render without base layout
    if request.GET.get("modal"):
        return render(request, "portal/payslip_partial.html", {
            "emp": emp,
            "payslip": payslip,
            "period_days": period_days,
            "net_salary_words": net_salary_words,
            "currency_code": "PKR",
        })

    return render(request, "portal/payslip_detail.html", {
        "emp": emp,
        "payslip": payslip,
        "period_days": period_days,
        "net_salary_words": net_salary_words,
        "currency_code": "PKR",
    })


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Punch (check-in / check-out from dashboard)
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@login_required(login_url="/portal/login/")
def portal_punch(request):
    if request.method != "POST":
        return redirect("portal:dashboard")

    emp = _get_employee(request)
    if emp is None:
        return redirect("/admin/")

    today = timezone.localdate()
    now_time = timezone.localtime().time().replace(second=0, microsecond=0)
    punch_type = request.POST.get("punch_type")
    record = AttendanceRecord.objects.filter(employee=emp, date=today).first()

    if punch_type == "in":
        if record and record.check_in:
            messages.error(request, "You have already checked in today.")
        else:
            record, _ = AttendanceRecord.objects.get_or_create(
                employee=emp,
                date=today,
                defaults={
                    "status": AttendanceRecord.StatusChoices.PRESENT,
                    "notes": "Checked in via Portal App",
                },
            )
            record.check_in = now_time
            if record.status not in (
                AttendanceRecord.StatusChoices.PRESENT,
                AttendanceRecord.StatusChoices.HALF_DAY,
            ):
                record.status = AttendanceRecord.StatusChoices.PRESENT
            flags = compute_attendance_flags(emp, now_time, None)
            record.is_late = flags["is_late"]
            record.is_early_checkout = False
            record.notes = "Checked in via Portal App"
            record.save()
            messages.success(request, "Checked in successfully.")

    elif punch_type == "out":
        if not record or not record.check_in:
            messages.error(request, "Please check in first.")
        elif record.check_out:
            messages.error(request, "You have already checked out today.")
        else:
            record.check_out = now_time
            flags = compute_attendance_flags(emp, record.check_in, now_time)
            record.is_late = flags["is_late"]
            record.is_early_checkout = flags["is_early_checkout"]
            record.notes = (record.notes or "") + " | Checked out via Portal App"
            record.save()
            messages.success(request, "Checked out successfully.")

    return redirect("portal:dashboard")


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Manager Dashboard
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

_MANAGER_ROLES = [EmployeeProfile.RoleChoices.MANAGER, EmployeeProfile.RoleChoices.APPROVER]


@login_required(login_url="/portal/login/")
def portal_manager_dashboard(request):
    emp = _get_employee(request)
    if emp is None:
        return redirect("/admin/")
    if emp.role not in _MANAGER_ROLES and not request.user.is_superuser:
        return redirect("portal:dashboard")

    today = timezone.localdate()
    year, month = today.year, today.month
    _, last_day = calendar.monthrange(year, month)
    month_start = date(year, month, 1)
    month_end = date(year, month, last_day)

    # Manager's own data (for punch widget + personal stats)
    own_stats, own_record_map = _month_stats(emp, year, month)
    today_record = own_record_map.get(today)
    att_pct = round(own_stats["present"] / own_stats["working_days"] * 100) if own_stats["working_days"] else 0

    # Team members
    team = list(
        EmployeeProfile.objects.filter(
            reporting_manager=emp,
            employment_status=EmployeeProfile.EmploymentStatusChoices.ACTIVE,
        ).order_by("department", "full_name")
    )
    team_ids = [m.pk for m in team]

    # Today's attendance for team (single query)
    today_recs = {
        r.employee_id: r
        for r in AttendanceRecord.objects.filter(employee_id__in=team_ids, date=today)
    }

    # Monthly attendance stats for team (batch)
    cap_date = min(today, month_end)
    month_stats_qs = (
        AttendanceRecord.objects.filter(
            employee_id__in=team_ids,
            date__range=(month_start, cap_date),
        )
        .values("employee_id")
        .annotate(
            present=Count(Case(When(status=AttendanceRecord.StatusChoices.PRESENT, then=1), output_field=IntegerField())),
            absent=Count(Case(When(status=AttendanceRecord.StatusChoices.ABSENT, then=1), output_field=IntegerField())),
            leave=Count(Case(
                When(status__in=[
                    AttendanceRecord.StatusChoices.ON_LEAVE_PAID,
                    AttendanceRecord.StatusChoices.ON_LEAVE_UNPAID,
                ], then=1),
                output_field=IntegerField(),
            )),
        )
    )
    month_stats_map = {r["employee_id"]: r for r in month_stats_qs}

    # Working days so far this month
    working_days_so_far = sum(
        1 for i in range((cap_date - month_start).days + 1)
        if (month_start + timedelta(days=i)).weekday() < 5
    )

    # Latest payslip for each team member (batch)
    latest_payslips = {}
    for ps in (
        Payslip.objects.filter(employee_id__in=team_ids)
        .select_related("payroll_run")
        .order_by("-payroll_run__year", "-payroll_run__month")
    ):
        if ps.employee_id not in latest_payslips:
            latest_payslips[ps.employee_id] = ps

    # Build team rows
    team_rows = []
    for member in team:
        ms = month_stats_map.get(member.pk, {})
        present = ms.get("present", 0)
        pct = round(present / working_days_so_far * 100) if working_days_so_far else 0
        team_rows.append({
            "employee": member,
            "today_record": today_recs.get(member.pk),
            "present_days": present,
            "absent_days": ms.get("absent", 0),
            "leave_days": ms.get("leave", 0),
            "att_pct": pct,
            "latest_payslip": latest_payslips.get(member.pk),
        })

    # Pending / manager-approved leave requests (regular + short leave combined)
    from leaves.models import ShortLeaveRequest as _SLR
    pending_leaves = list(
        LeaveRequest.objects.filter(
            employee__reporting_manager=emp,
            status=LeaveRequest.StatusChoices.PENDING,
        ).select_related("employee", "leave_type", "allocation").order_by("-created_at")
    )
    pending_short_leaves = list(
        _SLR.objects.filter(
            employee__reporting_manager=emp,
            status=_SLR.StatusChoices.PENDING,
        ).select_related("employee").order_by("-created_at")
    )
    # Tag each so the template knows which type it is
    for lr in pending_leaves:
        lr.is_short_leave = False
    for sl in pending_short_leaves:
        sl.is_short_leave = True
        sl.leave_type = type("FakeLT", (), {"name": f"Short Leave â€” {sl.period}"})()
        sl.allocation = None
        sl.number_of_days = 0.5
    # Merge and sort by created_at
    import operator
    pending_leaves = sorted(pending_leaves + pending_short_leaves, key=operator.attrgetter("created_at"), reverse=True)

    awaiting_admin_leaves = list(
        LeaveRequest.objects.filter(
            employee__reporting_manager=emp,
            status=LeaveRequest.StatusChoices.MANAGER_APPROVED,
        ).select_related("employee", "leave_type").order_by("-created_at")[:10]
    )
    for lr in awaiting_admin_leaves:
        lr.is_short_leave = False

    # Manager's own leave / payslip data
    own_allocations = (
        LeaveAllocation.objects.filter(employee=emp, year=year)
        .select_related("leave_type")
        .order_by("leave_type__name")
    )
    leave_types = LeaveType.objects.filter(is_active=True).order_by("name")
    own_latest_payslip = (
        Payslip.objects.filter(employee=emp)
        .select_related("payroll_run")
        .order_by("-payroll_run__year", "-payroll_run__month")
        .first()
    )
    team_present_today = sum(1 for r in today_recs.values() if r.check_in)

    return render(request, "portal/manager_dashboard.html", {
        "emp": emp,
        "today": today,
        "today_record": today_record,
        "att_pct": att_pct,
        "own_stats": own_stats,
        "team_rows": team_rows,
        "team_count": len(team),
        "team_present_today": team_present_today,
        "pending_leaves": pending_leaves,
        "pending_count": len(pending_leaves),
        "awaiting_admin_leaves": awaiting_admin_leaves,
        "own_allocations": own_allocations,
        "leave_types": leave_types,
        "own_latest_payslip": own_latest_payslip,
        "month_label": today.strftime("%B %Y"),
        "today_str": today.isoformat(),
        "working_days_so_far": working_days_so_far,
    })


@login_required(login_url="/portal/login/")
def portal_manager_attendance(request):
    emp = _get_employee(request)
    if emp is None:
        return redirect("/admin/")
    if emp.role not in _MANAGER_ROLES and not request.user.is_superuser:
        return redirect("portal:dashboard")

    today = timezone.localdate()
    try:
        year = int(request.GET.get("year", today.year))
        month = int(request.GET.get("month", today.month))
    except ValueError:
        year, month = today.year, today.month
    month = max(1, min(12, month))

    prev_month = month - 1 or 12
    prev_year = year - 1 if month == 1 else year
    next_month = month % 12 + 1
    next_year = year + 1 if month == 12 else year

    _, last_day = calendar.monthrange(year, month)
    start = date(year, month, 1)
    end = date(year, month, last_day)

    holidays = PublicHoliday.dates_in_range(start, end)
    from attendance.models import CompanyWFHDay
    company_wfh_dates = CompanyWFHDay.dates_in_range(start, end)

    # Build day columns list
    days = [start + timedelta(days=i) for i in range(last_day)]

    # Team members
    team = list(
        EmployeeProfile.objects.filter(
            reporting_manager=emp,
            employment_status=EmployeeProfile.EmploymentStatusChoices.ACTIVE,
        ).order_by("department", "full_name")
    )
    team_ids = [m.pk for m in team]

    # All records for team in this month
    all_records = AttendanceRecord.objects.filter(
        employee_id__in=team_ids, date__range=(start, end)
    )
    # Map: employee_id -> {date -> record}
    rec_map = {}
    for r in all_records:
        rec_map.setdefault(r.employee_id, {})[r.date] = r

    def _cell_status(day, rec):
        if day.weekday() >= 5:
            return "weekend"
        if day in holidays and not rec:
            return "holiday"
        if rec:
            s = rec.status
            if s == AttendanceRecord.StatusChoices.PRESENT:
                return "present"
            elif s == AttendanceRecord.StatusChoices.ABSENT:
                return "absent"
            elif s in (
                AttendanceRecord.StatusChoices.ON_LEAVE_PAID,
                AttendanceRecord.StatusChoices.ON_LEAVE_UNPAID,
                AttendanceRecord.StatusChoices.ON_HOURLY_LEAVE,
            ):
                return "leave"
            elif s == AttendanceRecord.StatusChoices.WORK_FROM_HOME:
                return "wfh"
            elif s == AttendanceRecord.StatusChoices.PUBLIC_HOLIDAY:
                return "holiday"
            elif s == AttendanceRecord.StatusChoices.HALF_DAY:
                return "half_day"
            return "present"
        if day in company_wfh_dates:
            return "wfh"
        if day > today:
            return "future"
        return "not_recorded"

    # Build rows: one per team member
    rows = []
    for member in team:
        member_recs = rec_map.get(member.pk, {})
        cells = []
        p = a = l = w = 0
        for day in days:
            rec = member_recs.get(day)
            st = _cell_status(day, rec)
            if st == "present": p += 1
            elif st == "absent": a += 1
            elif st == "leave": l += 1
            elif st == "wfh": w += 1
            cells.append({"day": day, "status": st, "record": rec})
        rows.append({"employee": member, "cells": cells, "present": p, "absent": a, "leave": l, "wfh": w})

    return render(request, "portal/manager_attendance.html", {
        "emp": emp,
        "days": days,
        "rows": rows,
        "today": today,
        "year": year,
        "month": month,
        "month_label": date(year, month, 1).strftime("%B %Y"),
        "prev_year": prev_year,
        "prev_month": prev_month,
        "next_year": next_year,
        "next_month": next_month,
        "holidays": holidays,
        "team_count": len(team),
    })


@login_required(login_url="/portal/login/")
def portal_manager_leave_action(request, pk):
    if request.method != "POST":
        return redirect("portal:manager_dashboard")

    emp = _get_employee(request)
    if emp is None:
        return redirect("/admin/")
    if emp.role not in _MANAGER_ROLES and not request.user.is_superuser:
        messages.error(request, "You don't have permission to approve leaves.")
        return redirect("portal:manager_dashboard")

    action = request.POST.get("action")
    remarks = request.POST.get("remarks", "").strip()

    try:
        lr = LeaveRequest.objects.select_related("employee", "leave_type").get(
            pk=pk,
            employee__reporting_manager=emp,
            status=LeaveRequest.StatusChoices.PENDING,
        )
    except LeaveRequest.DoesNotExist:
        messages.error(request, "Leave request not found or already processed.")
        return redirect("portal:manager_dashboard")

    if action == "approve":
        lr.status = LeaveRequest.StatusChoices.MANAGER_APPROVED
        lr.manager_approved_by = emp
        if remarks:
            lr.remarks = remarks
        lr.save()
        messages.success(
            request,
            f"Leave approved for {lr.employee.full_name}. Forwarded to HR/Admin for final approval."
        )
    elif action == "reject":
        lr.status = LeaveRequest.StatusChoices.REJECTED
        if remarks:
            lr.remarks = remarks
        lr.save()
        messages.warning(request, f"Leave request for {lr.employee.full_name} rejected.")

    return redirect("portal:manager_dashboard")


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# HR Admin Panel
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _hr_check(request):
    """Return True if the user has HR-level access."""
    if request.user.is_superuser:
        return True
    emp = getattr(request.user, "employee_profile", None)
    if emp and emp.role in [EmployeeProfile.RoleChoices.SUPER_ADMIN, EmployeeProfile.RoleChoices.APPROVER]:
        return True
    return False


@login_required(login_url="/portal/login/")
def hr_dashboard(request):
    if not _hr_check(request):
        return redirect("portal:dashboard")

    today = timezone.localdate()
    year, month = today.year, today.month
    _, last_day = calendar.monthrange(year, month)
    month_start = date(year, month, 1)
    month_end = date(year, month, last_day)

    total_employees = EmployeeProfile.objects.filter(
        employment_status=EmployeeProfile.EmploymentStatusChoices.ACTIVE
    ).count()

    today_records = AttendanceRecord.objects.filter(date=today)
    present_today = today_records.filter(status=AttendanceRecord.StatusChoices.PRESENT).count()
    checked_in_today = today_records.filter(check_in__isnull=False).count()
    late_today = today_records.filter(is_late=True).count()
    on_leave_today = today_records.filter(status__in=[
        AttendanceRecord.StatusChoices.ON_LEAVE_PAID,
        AttendanceRecord.StatusChoices.ON_LEAVE_UNPAID,
    ]).count()

    pending_leaves = LeaveRequest.objects.filter(status=LeaveRequest.StatusChoices.PENDING).count()
    manager_approved_leaves = LeaveRequest.objects.filter(status=LeaveRequest.StatusChoices.MANAGER_APPROVED).count()

    from django.db.models import Count as DjCount
    dept_counts_raw = list(
        EmployeeProfile.objects
        .filter(employment_status=EmployeeProfile.EmploymentStatusChoices.ACTIVE)
        .values("department")
        .annotate(count=DjCount("id"))
        .order_by("-count")[:8]
    )

    # Present count per department for today
    today_present_ids = set(
        AttendanceRecord.objects.filter(date=today, status=AttendanceRecord.StatusChoices.PRESENT)
        .values_list("employee_id", flat=True)
    )
    dept_present_map = {}
    for emp_row in (
        EmployeeProfile.objects.filter(
            employment_status=EmployeeProfile.EmploymentStatusChoices.ACTIVE,
            department__in=[d["department"] for d in dept_counts_raw],
        ).values("id", "department")
    ):
        dept = emp_row["department"]
        dept_present_map.setdefault(dept, 0)
        if emp_row["id"] in today_present_ids:
            dept_present_map[dept] += 1

    dept_counts = [
        {
            "department": d["department"],
            "count": d["count"],
            "present": dept_present_map.get(d["department"], 0),
        }
        for d in dept_counts_raw
    ]

    # Annual salary + tax chart data (current year)
    from salary.models import PayrollRun, Payslip as _Payslip
    from django.db.models import Sum as DjSum
    annual_salary = []
    annual_tax = []
    MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
    for m in range(1, 13):
        agg = _Payslip.objects.filter(
            payroll_run__year=year, payroll_run__month=m
        ).aggregate(gs=DjSum("gross_salary"), it=DjSum("income_tax"))
        annual_salary.append(float(agg["gs"] or 0))
        annual_tax.append(float(agg["it"] or 0))

    # Attendance by period for pie chart
    import json as _json
    cap = min(today, month_end)
    # Monthly
    monthly_att = AttendanceRecord.objects.filter(date__range=(month_start, cap)).aggregate(
        present=DjCount("id", filter=Q(status=AttendanceRecord.StatusChoices.PRESENT)),
        absent=DjCount("id", filter=Q(status=AttendanceRecord.StatusChoices.ABSENT)),
        leave=DjCount("id", filter=Q(status__in=[
            AttendanceRecord.StatusChoices.ON_LEAVE_PAID,
            AttendanceRecord.StatusChoices.ON_LEAVE_UNPAID,
        ])),
        wfh=DjCount("id", filter=Q(status=AttendanceRecord.StatusChoices.WORK_FROM_HOME)),
    )
    # Quarterly (last 3 months)
    q_start = date(year, max(1, month - 2), 1)
    quarterly_att = AttendanceRecord.objects.filter(date__range=(q_start, cap)).aggregate(
        present=DjCount("id", filter=Q(status=AttendanceRecord.StatusChoices.PRESENT)),
        absent=DjCount("id", filter=Q(status=AttendanceRecord.StatusChoices.ABSENT)),
        leave=DjCount("id", filter=Q(status__in=[
            AttendanceRecord.StatusChoices.ON_LEAVE_PAID,
            AttendanceRecord.StatusChoices.ON_LEAVE_UNPAID,
        ])),
        wfh=DjCount("id", filter=Q(status=AttendanceRecord.StatusChoices.WORK_FROM_HOME)),
    )
    # Half-yearly (last 6 months)
    h_start = date(year, max(1, month - 5), 1)
    halfyearly_att = AttendanceRecord.objects.filter(date__range=(h_start, cap)).aggregate(
        present=DjCount("id", filter=Q(status=AttendanceRecord.StatusChoices.PRESENT)),
        absent=DjCount("id", filter=Q(status=AttendanceRecord.StatusChoices.ABSENT)),
        leave=DjCount("id", filter=Q(status__in=[
            AttendanceRecord.StatusChoices.ON_LEAVE_PAID,
            AttendanceRecord.StatusChoices.ON_LEAVE_UNPAID,
        ])),
        wfh=DjCount("id", filter=Q(status=AttendanceRecord.StatusChoices.WORK_FROM_HOME)),
    )

    from salary.models import PayrollRun
    latest_run = PayrollRun.objects.order_by("-year", "-month").first()

    recent_pending = list(
        LeaveRequest.objects.filter(
            status__in=[LeaveRequest.StatusChoices.PENDING, LeaveRequest.StatusChoices.MANAGER_APPROVED]
        ).select_related("employee", "leave_type").order_by("-created_at")[:8]
    )

    working_days_so_far = sum(
        1 for i in range((cap - month_start).days + 1)
        if (month_start + timedelta(days=i)).weekday() < 5
    )
    total_expected = total_employees * working_days_so_far if working_days_so_far else 1
    total_present_month = AttendanceRecord.objects.filter(
        date__range=(month_start, cap),
        status=AttendanceRecord.StatusChoices.PRESENT,
    ).count()
    att_rate = round(total_present_month / total_expected * 100) if total_expected else 0

    new_hires = EmployeeProfile.objects.filter(joining_date__range=(month_start, month_end)).count()

    import json as _json
    return render(request, "portal/hr/dashboard.html", {
        "total_employees": total_employees,
        "present_today": present_today,
        "checked_in_today": checked_in_today,
        "late_today": late_today,
        "on_leave_today": on_leave_today,
        "pending_leaves": pending_leaves,
        "manager_approved_leaves": manager_approved_leaves,
        "dept_counts": dept_counts,
        "latest_run": latest_run,
        "recent_pending": recent_pending,
        "att_rate": att_rate,
        "working_days_so_far": working_days_so_far,
        "new_hires": new_hires,
        "today": today,
        "month_label": today.strftime("%B %Y"),
        # Charts
        "chart_months_json": _json.dumps(MONTHS),
        "chart_salary_json": _json.dumps(annual_salary),
        "chart_tax_json": _json.dumps(annual_tax),
        "pie_monthly_json": _json.dumps([
            monthly_att["present"] or 0, monthly_att["absent"] or 0,
            monthly_att["leave"] or 0, monthly_att["wfh"] or 0,
        ]),
        "pie_quarterly_json": _json.dumps([
            quarterly_att["present"] or 0, quarterly_att["absent"] or 0,
            quarterly_att["leave"] or 0, quarterly_att["wfh"] or 0,
        ]),
        "pie_halfyearly_json": _json.dumps([
            halfyearly_att["present"] or 0, halfyearly_att["absent"] or 0,
            halfyearly_att["leave"] or 0, halfyearly_att["wfh"] or 0,
        ]),
    })


@login_required(login_url="/portal/login/")
def hr_employees(request):
    if not _hr_check(request):
        return redirect("portal:dashboard")

    from django.db.models import Q as DjQ
    q = request.GET.get("q", "").strip()
    dept = request.GET.get("dept", "")
    status_f = request.GET.get("status", "")
    role_f = request.GET.get("role", "")

    from django.db.models import Case, When, Value, IntegerField as _IntF
    qs = EmployeeProfile.objects.select_related("reporting_manager").order_by(
        Case(When(employment_status="Active", then=Value(0)), default=Value(1), output_field=_IntF()),
        "full_name",
    )
    if q:
        qs = qs.filter(
            DjQ(full_name__icontains=q) | DjQ(employee_code__icontains=q) |
            DjQ(official_email__icontains=q) | DjQ(department__icontains=q) |
            DjQ(designation__icontains=q)
        )
    if dept:
        qs = qs.filter(department=dept)
    if status_f:
        qs = qs.filter(employment_status=status_f)
    if role_f:
        qs = qs.filter(role=role_f)

    departments = (
        EmployeeProfile.objects.values_list("department", flat=True)
        .distinct().order_by("department")
    )

    today = timezone.localdate()
    emp_list = list(qs)
    today_recs = {
        r.employee_id: r
        for r in AttendanceRecord.objects.filter(date=today, employee_id__in=[e.pk for e in emp_list])
    }

    employees = [
        {"emp": emp, "today_rec": today_recs.get(emp.pk)}
        for emp in emp_list
    ]

    return render(request, "portal/hr/employees.html", {
        "employees": employees,
        "departments": departments,
        "q": q, "dept": dept, "status_f": status_f, "role_f": role_f,
        "status_choices": EmployeeProfile.EmploymentStatusChoices.choices,
        "role_choices": EmployeeProfile.RoleChoices.choices,
        "total": len(employees),
        "today": today,
    })


@login_required(login_url="/portal/login/")
def hr_employees_bulk_delete(request):
    if not _hr_check(request):
        return redirect("portal:dashboard")
    if request.method != "POST":
        return redirect("portal:hr_employees")
    ids = request.POST.getlist("employee_ids")
    if ids:
        EmployeeProfile.objects.filter(pk__in=ids).delete()
    return redirect("portal:hr_employees")


@login_required(login_url="/portal/login/")
def hr_employee_detail(request, pk):
    if not _hr_check(request):
        return redirect("portal:dashboard")

    from salary.models import Payslip
    emp = get_object_or_404(EmployeeProfile, pk=pk)
    today = timezone.localdate()
    year = today.year

    stats, record_map = _month_stats(emp, today.year, today.month)
    today_record = record_map.get(today)

    allocations = (
        LeaveAllocation.objects.filter(employee=emp, year=year)
        .select_related("leave_type").order_by("leave_type__name")
    )
    recent_leaves = (
        LeaveRequest.objects.filter(employee=emp)
        .select_related("leave_type").order_by("-created_at")[:10]
    )
    payslips = (
        Payslip.objects.filter(employee=emp)
        .select_related("payroll_run")
        .order_by("-payroll_run__year", "-payroll_run__month")[:6]
    )
    att_pct = round(stats["present"] / stats["working_days"] * 100) if stats["working_days"] else 0

    return render(request, "portal/hr/employee_detail.html", {
        "emp": emp, "today": today, "today_record": today_record,
        "stats": stats, "att_pct": att_pct,
        "allocations": allocations, "recent_leaves": recent_leaves,
        "payslips": payslips,
        "month_label": today.strftime("%B %Y"),
    })


@login_required
def hr_employee_edit(request, pk=None):
    if not _hr_check(request):
        return redirect("portal:dashboard")
    from django.contrib.auth import get_user_model
    from decimal import Decimal, InvalidOperation
    from salary.models import SalarySetup
    from salary.services import q as salary_q
    User = get_user_model()
    emp = get_object_or_404(EmployeeProfile, pk=pk) if pk else None
    all_employees = EmployeeProfile.objects.order_by("full_name")
    all_shifts = __import__("attendance.models", fromlist=["Shift"]).Shift.objects.filter(is_active=True).order_by("name")
    errors = {}

    # fetch existing salary setup if editing
    salary_setup = None
    if emp:
        try:
            salary_setup = SalarySetup.objects.get(employee=emp)
        except SalarySetup.DoesNotExist:
            pass

    if request.method == "POST":
        p = request.POST
        step = p.get("step", "all")
        try:
            if not emp:
                username = p.get("username", "").strip()
                email = p.get("official_email", "").strip()
                password = p.get("password", "").strip()
                send_setup_email = p.get("send_setup_email") == "on"
                if not username:
                    raise ValueError("Username is required to create a new employee.")
                if not password and not send_setup_email:
                    raise ValueError("Either enter a password or check 'Send password setup email'.")
                # create_user with password=None already sets an unusable password
                user = User.objects.create_user(username=username, email=email, password=password or None)
                # The post_save signal auto-creates a placeholder EmployeeProfile.
                # Reuse it instead of creating a duplicate (which would fail the unique constraint).
                try:
                    emp = EmployeeProfile.objects.get(user=user)
                except EmployeeProfile.DoesNotExist:
                    emp = EmployeeProfile(user=user)

            # â”€â”€ Step 1: Personal â”€â”€
            emp.full_name = p.get("full_name", emp.full_name if emp.pk else "").strip()
            emp.gender = p.get("gender", emp.gender if emp.pk else "")
            from datetime import date as _date
            def parse_date(val):
                if not val:
                    return None
                if isinstance(val, _date):
                    return val
                try:
                    from datetime import datetime as _dt
                    return _dt.strptime(val.strip(), "%Y-%m-%d").date()
                except (ValueError, AttributeError):
                    return None

            emp.date_of_birth = parse_date(p.get("date_of_birth")) or (emp.date_of_birth if emp.pk else None)
            emp.marital_status = p.get("marital_status", emp.marital_status if emp.pk else "")
            emp.personal_email = p.get("personal_email", emp.personal_email if emp.pk else "").strip()
            emp.official_email = p.get("official_email", emp.official_email if emp.pk else "").strip()
            emp.personal_phone = p.get("personal_phone", emp.personal_phone if emp.pk else "").strip()
            emp.emergency_contact_name = p.get("emergency_contact_name", emp.emergency_contact_name if emp.pk else "").strip()
            emp.emergency_contact_number = p.get("emergency_contact_number", emp.emergency_contact_number if emp.pk else "").strip()
            emp.current_address = p.get("current_address", emp.current_address if emp.pk else "").strip()
            emp.city = p.get("city", emp.city if emp.pk else "").strip()
            emp.country = p.get("country", emp.country if emp.pk else "Pakistan").strip()
            emp.cnic = p.get("cnic", emp.cnic if emp.pk else "").strip()
            # Blank or auto/import placeholder â†’ store "-"
            if not emp.cnic or emp.cnic.startswith("IMPORT-") or emp.cnic.startswith("AUTO-"):
                emp.cnic = "-"
            emp.passport_number = p.get("passport_number", emp.passport_number if emp.pk else "").strip() or "-"
            if request.FILES.get("profile_photo"):
                photo_file = request.FILES["profile_photo"]
                allowed_image_types = ("image/jpeg", "image/png", "image/gif", "image/webp")
                if photo_file.content_type not in allowed_image_types:
                    raise ValueError(f"Unsupported image type: {photo_file.content_type}. Use JPG, PNG, GIF or WEBP.")
                emp.profile_photo = photo_file
            # CNIC copy document
            if request.FILES.get("cnic_copy"):
                emp.cnic_copy = request.FILES["cnic_copy"]

            # â”€â”€ Step 2: Employment â”€â”€
            emp.employee_code = p.get("employee_code", emp.employee_code if emp.pk else "").strip()
            emp.department = p.get("department", emp.department if emp.pk else "").strip()
            emp.designation = p.get("designation", emp.designation if emp.pk else "").strip()
            emp.employment_type = p.get("employment_type", emp.employment_type if emp.pk else "Permanent")
            emp.employment_status = p.get("employment_status", emp.employment_status if emp.pk else "Active")
            emp.joining_date = parse_date(p.get("joining_date")) or (emp.joining_date if emp.pk else None)
            emp.hire_date = parse_date(p.get("hire_date")) or (emp.hire_date if emp.pk else None)
            emp.confirmation_date = parse_date(p.get("confirmation_date")) or (emp.confirmation_date if emp.pk else None)
            manager_pk = p.get("reporting_manager")
            emp.reporting_manager_id = manager_pk if manager_pk else None
            emp.team = p.get("team", emp.team if emp.pk else "").strip() or "-"
            emp.work_location = p.get("work_location", emp.work_location if emp.pk else "").strip() or "-"
            emp.role = p.get("role", emp.role if emp.pk else "Employee")
            shift_pk = p.get("shift_master")
            emp.shift_master_id = shift_pk if shift_pk else None
            emp.remarks = p.get("remarks", emp.remarks if emp.pk else "").strip()
            # Documents
            for doc_field in ("resume", "offer_letter", "contract"):
                if request.FILES.get(doc_field):
                    setattr(emp, doc_field, request.FILES[doc_field])

            # â”€â”€ Step 3: Salary & Payment â”€â”€
            def dec(field, default="0"):
                try:
                    return Decimal(p.get(field, default) or default)
                except InvalidOperation:
                    return Decimal(default)

            gross = dec("gross_salary_input")
            emp.payment_mode = p.get("payment_mode", emp.payment_mode if emp.pk else "Bank")
            emp.bank_name = p.get("bank_name", emp.bank_name if emp.pk else "").strip() or "-"
            emp.account_title = p.get("account_title", emp.account_title if emp.pk else "").strip() or "-"
            emp.account_number = p.get("account_number", emp.account_number if emp.pk else "").strip() or "-"
            emp.iban = p.get("iban", emp.iban if emp.pk else "").strip() or "-"
            # Also store basic salary on employee profile
            if gross > 0:
                emp.basic_salary = salary_q(gross * Decimal("0.60"))
                emp.house_rent_allowance = salary_q(gross * Decimal("0.20"))
                emp.medical_allowance = salary_q(gross * Decimal("0.10"))
                emp.conveyance_allowance = dec("conveyance_allowance")
                emp.other_allowance = dec("other_allowance")

            emp.save()

            # Sync role permissions for new employees
            if not pk:
                from accounts.services import sync_user_role
                sync_user_role(emp.user, emp.role, emp.employment_status)

            # Send password setup email for new employees when no password was set
            if not pk and send_setup_email and emp.user.email:
                from accounts.email_utils import send_password_setup_email
                send_password_setup_email(request, emp.user)

            # â”€â”€ Sync to SalarySetup â”€â”€
            # Derive gross from form field; fall back to deriving from basic salary on profile
            effective_gross = gross
            if effective_gross <= 0 and (emp.basic_salary or Decimal("0")) > 0:
                effective_gross = salary_q((emp.basic_salary or Decimal("0")) / Decimal("0.60"))

            if effective_gross > 0:
                setup, _ = SalarySetup.objects.get_or_create(employee=emp)
                setup.gross_salary_input = effective_gross
                setup.basic_salary = salary_q(effective_gross * Decimal("0.60"))
                setup.house_rent_allowance = salary_q(effective_gross * Decimal("0.20"))
                setup.utility_allowance = salary_q(effective_gross * Decimal("0.10"))
                setup.medical_allowance = salary_q(effective_gross * Decimal("0.10"))
                setup.conveyance_allowance = dec("conveyance_allowance")
                setup.other_allowance = dec("other_allowance")
                setup.payment_mode = emp.payment_mode
                setup.bank_name = emp.bank_name
                setup.account_title = emp.account_title
                setup.account_number = emp.account_number
                ntn = p.get("ntn_no", "").strip()
                if ntn:
                    setup.ntn_no = ntn
                setup.eobi_contribution = dec("eobi_contribution")
                setup.provident_fund_deduction = dec("provident_fund_deduction")
                setup.loan_installment = dec("loan_installment")
                setup.misc_deduction = dec("misc_deduction")
                setup.advance_salary_repayment = dec("advance_salary_repayment")
                setup.is_active = True
                setup.save()
                salary_setup = setup

            messages.success(request, f"{'Employee created' if not pk else 'Employee updated'}: {emp.full_name}")
            return redirect("portal:hr_employees")
        except Exception as e:
            errors["general"] = str(e)

    gender_choices = EmployeeProfile.GenderChoices.choices if hasattr(EmployeeProfile, "GenderChoices") else [("Male","Male"),("Female","Female"),("Other","Other")]
    marital_choices = [("Single","Single"),("Married","Married"),("Divorced","Divorced"),("Widowed","Widowed")]
    type_choices = EmployeeProfile.EmploymentTypeChoices.choices if hasattr(EmployeeProfile, "EmploymentTypeChoices") else [("Permanent","Permanent"),("Probation","Probation"),("Contract","Contract"),("Intern","Intern")]
    status_choices = EmployeeProfile.EmploymentStatusChoices.choices
    role_choices = EmployeeProfile.RoleChoices.choices
    payment_choices = [
        ("Bank", "Bank"),
        ("Cash", "Cash"),
        ("Cheque", "Cheque"),
        ("Online Transfer", "Online Transfer"),
        ("Other", "Other"),
        ("-", "-"),
    ]

    dept_list = list(EmployeeProfile.objects.values_list("department", flat=True).exclude(department="").distinct().order_by("department"))
    desig_list = list(EmployeeProfile.objects.values_list("designation", flat=True).exclude(designation="").distinct().order_by("designation"))
    location_list = list(EmployeeProfile.objects.values_list("work_location", flat=True).exclude(work_location="").distinct().order_by("work_location"))

    return render(request, "portal/hr/employee_form.html", {
        "emp": emp,
        "salary_setup": salary_setup,
        "errors": errors,
        "all_employees": all_employees,
        "all_shifts": all_shifts,
        "gender_choices": gender_choices,
        "marital_choices": marital_choices,
        "type_choices": type_choices,
        "status_choices": status_choices,
        "role_choices": role_choices,
        "payment_choices": payment_choices,
        "dept_list": dept_list,
        "desig_list": desig_list,
        "location_list": location_list,
        "cnic_display": (emp.cnic if emp and emp.cnic and not emp.cnic.startswith("IMPORT-") and not emp.cnic.startswith("AUTO-") else ""),
    })


@login_required(login_url="/portal/login/")
def hr_attendance(request):
    if not _hr_check(request):
        return redirect("portal:dashboard")

    today = timezone.localdate()
    try:
        year = int(request.GET.get("year", today.year))
        month = int(request.GET.get("month", today.month))
    except ValueError:
        year, month = today.year, today.month
    month = max(1, min(12, month))

    dept_filter = request.GET.get("dept", "")
    prev_month = month - 1 or 12
    prev_year = year - 1 if month == 1 else year
    next_month = month % 12 + 1
    next_year = year + 1 if month == 12 else year

    _, last_day = calendar.monthrange(year, month)
    start = date(year, month, 1)
    end = date(year, month, last_day)

    holidays = PublicHoliday.dates_in_range(start, end)
    from attendance.models import CompanyWFHDay
    company_wfh_dates = CompanyWFHDay.dates_in_range(start, end)
    days = [start + timedelta(days=i) for i in range(last_day)]

    qs = EmployeeProfile.objects.filter(
        employment_status=EmployeeProfile.EmploymentStatusChoices.ACTIVE
    ).order_by("department", "full_name")
    if dept_filter:
        qs = qs.filter(department=dept_filter)

    employees = list(qs)
    emp_ids = [e.pk for e in employees]

    rec_map = {}
    for r in AttendanceRecord.objects.filter(employee_id__in=emp_ids, date__range=(start, end)):
        rec_map.setdefault(r.employee_id, {})[r.date] = r

    def _cell(day, rec):
        if day.weekday() >= 5:
            return "weekend"
        if day in holidays and not rec:
            return "holiday"
        if rec:
            s = rec.status
            if s == AttendanceRecord.StatusChoices.PRESENT: return "present"
            elif s == AttendanceRecord.StatusChoices.ABSENT: return "absent"
            elif s in (AttendanceRecord.StatusChoices.ON_LEAVE_PAID,
                       AttendanceRecord.StatusChoices.ON_LEAVE_UNPAID,
                       AttendanceRecord.StatusChoices.ON_HOURLY_LEAVE): return "leave"
            elif s == AttendanceRecord.StatusChoices.WORK_FROM_HOME: return "wfh"
            elif s == AttendanceRecord.StatusChoices.PUBLIC_HOLIDAY: return "holiday"
            elif s == AttendanceRecord.StatusChoices.HALF_DAY: return "half_day"
            return "present"
        # Company-wide WFH day â€” leave takes priority (handled above); show for past and future
        if day in company_wfh_dates:
            return "wfh"
        return "future" if day > today else "not_recorded"

    rows = []
    for emp in employees:
        emp_recs = rec_map.get(emp.pk, {})
        cells = []
        p = a = l = w = 0
        for day in days:
            rec = emp_recs.get(day)
            st = _cell(day, rec)
            if st == "present": p += 1
            elif st == "absent": a += 1
            elif st == "leave": l += 1
            elif st == "wfh": w += 1
            cells.append({"day": day, "status": st, "record": rec})
        rows.append({"employee": emp, "cells": cells, "present": p, "absent": a, "leave": l, "wfh": w})

    departments = (
        EmployeeProfile.objects.filter(employment_status=EmployeeProfile.EmploymentStatusChoices.ACTIVE)
        .values_list("department", flat=True).distinct().order_by("department")
    )

    return render(request, "portal/hr/attendance.html", {
        "days": days, "rows": rows, "today": today,
        "year": year, "month": month,
        "month_label": date(year, month, 1).strftime("%B %Y"),
        "prev_year": prev_year, "prev_month": prev_month,
        "next_year": next_year, "next_month": next_month,
        "departments": list(departments), "dept_filter": dept_filter,
        "total_emp": len(employees),
    })


@login_required(login_url="/portal/login/")
def hr_leaves(request):
    if not _hr_check(request):
        return redirect("portal:dashboard")

    from django.db.models import Q as DjQ, Sum
    from datetime import date as _date, timedelta as _td
    import calendar as _cal

    tab = request.GET.get("tab", "pending")
    q = request.GET.get("q", "").strip()

    from leaves.models import ShortLeaveRequest as SLR

    counts = {
        "pending": (
            LeaveRequest.objects.filter(status=LeaveRequest.StatusChoices.PENDING).count() +
            SLR.objects.filter(status=SLR.StatusChoices.PENDING).count()
        ),
        "manager_approved": (
            LeaveRequest.objects.filter(status=LeaveRequest.StatusChoices.MANAGER_APPROVED).count() +
            SLR.objects.filter(status=SLR.StatusChoices.MANAGER_APPROVED).count()
        ),
        "approved": (
            LeaveRequest.objects.filter(status=LeaveRequest.StatusChoices.APPROVED).count() +
            SLR.objects.filter(status=SLR.StatusChoices.APPROVED).count()
        ),
        "rejected": (
            LeaveRequest.objects.filter(status=LeaveRequest.StatusChoices.REJECTED).count() +
            SLR.objects.filter(status=SLR.StatusChoices.REJECTED).count()
        ),
    }

    # â”€â”€ History tab: period-based filtering â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    if tab == "history":
        today = timezone.localdate()
        period = request.GET.get("period", "month")  # year | month | week

        if period == "year":
            try:
                year = int(request.GET.get("year", today.year))
            except ValueError:
                year = today.year
            start_date = _date(year, 1, 1)
            end_date = _date(year, 12, 31)
            prev_params = f"tab=history&period=year&year={year - 1}"
            next_params = f"tab=history&period=year&year={year + 1}"
            period_label = str(year)

        elif period == "week":
            try:
                year = int(request.GET.get("year", today.year))
                week = int(request.GET.get("week", today.isocalendar()[1]))
            except ValueError:
                year, week = today.year, today.isocalendar()[1]
            # ISO week start (Monday)
            start_date = _date.fromisocalendar(year, week, 1)
            end_date = start_date + _td(days=6)
            prev_week_start = start_date - _td(weeks=1)
            p_y, p_w, _ = prev_week_start.isocalendar()
            next_week_start = start_date + _td(weeks=1)
            n_y, n_w, _ = next_week_start.isocalendar()
            prev_params = f"tab=history&period=week&year={p_y}&week={p_w}"
            next_params = f"tab=history&period=week&year={n_y}&week={n_w}"
            period_label = f"Week {week}, {year} ({start_date.strftime('%b %d')} â€“ {end_date.strftime('%b %d, %Y')})"

        else:  # month (default)
            period = "month"
            try:
                year = int(request.GET.get("year", today.year))
                month = int(request.GET.get("month", today.month))
            except ValueError:
                year, month = today.year, today.month
            month = max(1, min(12, month))
            _, last_day = _cal.monthrange(year, month)
            start_date = _date(year, month, 1)
            end_date = _date(year, month, last_day)
            prev_m = month - 1 or 12
            prev_y = year - 1 if month == 1 else year
            next_m = month % 12 + 1
            next_y = year + 1 if month == 12 else year
            prev_params = f"tab=history&period=month&year={prev_y}&month={prev_m}"
            next_params = f"tab=history&period=month&year={next_y}&month={next_m}"
            period_label = start_date.strftime("%B %Y")

        qs = (
            LeaveRequest.objects.filter(from_date__gte=start_date, from_date__lte=end_date)
            .select_related("employee", "leave_type", "allocation", "approved_by", "manager_approved_by")
            .order_by("-from_date")
        )
        if q:
            qs = qs.filter(
                DjQ(employee__full_name__icontains=q) | DjQ(employee__employee_code__icontains=q)
            )

        # Summary stats for the period
        status_summary = {}
        type_summary = {}
        dept_summary = {}
        total_days = Decimal("0")
        for lr in qs:
            d = lr.number_of_days or 0
            total_days += Decimal(str(d))
            status_summary[lr.status] = status_summary.get(lr.status, 0) + d
            ltype = lr.leave_type.name if lr.leave_type else "Unknown"
            type_summary[ltype] = type_summary.get(ltype, 0) + d
            dept = lr.employee.department or "â€”"
            dept_summary[dept] = dept_summary.get(dept, 0) + d

        # Current period params for tab links
        if period == "year":
            period_params = f"period=year&year={year}"
        elif period == "week":
            period_params = f"period=week&year={year}&week={week}"
        else:
            period_params = f"period=month&year={year}&month={month}"

        return render(request, "portal/hr/leaves.html", {
            "leave_requests": list(qs), "tab": tab, "counts": counts, "q": q,
            "period": period, "period_label": period_label,
            "prev_params": prev_params, "next_params": next_params,
            "period_params": period_params,
            "status_summary": status_summary,
            "type_summary": sorted(type_summary.items(), key=lambda x: -x[1]),
            "dept_summary": sorted(dept_summary.items(), key=lambda x: -x[1]),
            "total_days": total_days,
            "start_date": start_date, "end_date": end_date,
            # year/month/week for form controls
            "sel_year": year,
            "sel_month": month if period == "month" else today.month,
            "sel_week": week if period == "week" else today.isocalendar()[1],
            "years_range": range(today.year - 4, today.year + 2),
            "months_range": [(i, _date(2000, i, 1).strftime("%B")) for i in range(1, 13)],
            "weeks_range": range(1, 54),
        })

    # â”€â”€ Status tabs â€” combine LeaveRequest + ShortLeaveRequest â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    status_map = {
        "pending":          LeaveRequest.StatusChoices.PENDING,
        "manager_approved": LeaveRequest.StatusChoices.MANAGER_APPROVED,
        "approved":         LeaveRequest.StatusChoices.APPROVED,
        "rejected":         LeaveRequest.StatusChoices.REJECTED,
    }
    status_val = status_map.get(tab, LeaveRequest.StatusChoices.PENDING)

    lr_qs = (
        LeaveRequest.objects.filter(status=status_val)
        .select_related("employee", "leave_type", "allocation", "approved_by", "manager_approved_by")
        .order_by("-created_at")
    )
    sl_qs = (
        SLR.objects.filter(status=status_val)
        .select_related("employee", "approved_by", "manager_approved_by")
        .order_by("-created_at")
    )
    if q:
        lr_qs = lr_qs.filter(DjQ(employee__full_name__icontains=q) | DjQ(employee__employee_code__icontains=q))
        sl_qs = sl_qs.filter(DjQ(employee__full_name__icontains=q) | DjQ(employee__employee_code__icontains=q))

    # Normalise both into a unified list for the template
    def _norm_lr(lr):
        return {
            "kind": "leave", "pk": lr.pk,
            "employee": lr.employee,
            "leave_type_name": lr.leave_type.name if lr.leave_type else "â€”",
            "from_date": lr.from_date, "to_date": lr.to_date,
            "duration": lr.number_of_days,
            "duration_label": "days",
            "time_info": None,
            "status": lr.status, "reason": lr.reason, "remarks": lr.remarks,
            "created_at": lr.created_at,
            "approved_by": lr.approved_by,
            "manager_approved_by": lr.manager_approved_by,
        }

    def _norm_sl(sl):
        return {
            "kind": "short_leave", "pk": sl.pk,
            "employee": sl.employee,
            "leave_type_name": f"Short Leave â€” {sl.period}",
            "from_date": sl.date, "to_date": sl.date,
            "duration": "Â½",
            "duration_label": "day",
            "time_info": f"{sl.from_time.strftime('%H:%M')} â€“ {sl.to_time.strftime('%H:%M')}",
            "status": sl.status, "reason": sl.reason, "remarks": sl.remarks,
            "created_at": sl.created_at,
            "approved_by": sl.approved_by,
            "manager_approved_by": sl.manager_approved_by,
        }

    combined = sorted(
        [_norm_lr(lr) for lr in lr_qs] + [_norm_sl(sl) for sl in sl_qs],
        key=lambda x: x["created_at"], reverse=True,
    )

    return render(request, "portal/hr/leaves.html", {
        "leave_requests": combined, "tab": tab, "counts": counts, "q": q,
    })


@login_required(login_url="/portal/login/")
def hr_leave_action(request, pk):
    if request.method != "POST":
        return redirect("portal:hr_leaves")
    if not _hr_check(request):
        return redirect("portal:dashboard")

    from attendance.services import sync_leave_request_to_attendance
    action = request.POST.get("action")
    remarks = request.POST.get("remarks", "").strip()
    next_tab = request.POST.get("next_tab", "pending")

    lr = get_object_or_404(LeaveRequest, pk=pk)
    profile = getattr(request.user, "employee_profile", None)

    if action == "approve":
        lr.status = LeaveRequest.StatusChoices.APPROVED
        lr.approved_by = profile
        if remarks:
            lr.remarks = remarks
        lr.save()
        sync_leave_request_to_attendance(lr)
        messages.success(request, f"Leave for {lr.employee.full_name} approved.")
    elif action == "reject":
        lr.status = LeaveRequest.StatusChoices.REJECTED
        if remarks:
            lr.remarks = remarks
        lr.save()
        messages.warning(request, f"Leave for {lr.employee.full_name} rejected.")

    return redirect(f"/portal/hr/leaves/?tab={next_tab}")


@login_required(login_url="/portal/login/")
def hr_payroll(request):
    if not _hr_check(request):
        return redirect("portal:dashboard")

    from salary.models import PayrollRun
    runs = list(PayrollRun.objects.order_by("-year", "-month"))

    return render(request, "portal/hr/payroll.html", {"runs": runs})


@login_required(login_url="/portal/login/")
def hr_payroll_detail(request, pk):
    if not _hr_check(request):
        return redirect("portal:dashboard")

    from django.db.models import Q as DjQ
    from salary.models import PayrollRun, Payslip
    run = get_object_or_404(PayrollRun, pk=pk)
    q = request.GET.get("q", "").strip()

    payslips = (
        Payslip.objects.filter(payroll_run=run)
        .select_related("employee").order_by("employee__full_name")
    )
    if q:
        payslips = payslips.filter(
            DjQ(employee__full_name__icontains=q) | DjQ(employee__employee_code__icontains=q)
        )
    payslips = list(payslips)
    total_gross = sum(p.gross_salary for p in payslips)
    total_net = sum(p.net_salary for p in payslips)
    total_deductions = sum(p.total_deductions for p in payslips)

    return render(request, "portal/hr/payroll_detail.html", {
        "run": run, "payslips": payslips,
        "total_gross": total_gross, "total_net": total_net,
        "total_deductions": total_deductions, "q": q,
    })


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# HR â€” Attendance Record CRUD
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@login_required(login_url="/portal/login/")
def hr_attendance_record_edit(request, pk=None):
    if not _hr_check(request):
        return redirect("portal:dashboard")

    from datetime import datetime as dt
    record = get_object_or_404(AttendanceRecord, pk=pk) if pk else None
    all_employees = EmployeeProfile.objects.filter(
        employment_status=EmployeeProfile.EmploymentStatusChoices.ACTIVE
    ).order_by("full_name")
    errors = {}

    if request.method == "POST":
        emp_id = request.POST.get("employee")
        date_str = request.POST.get("date", "")
        status = request.POST.get("status", "")
        check_in_str = request.POST.get("check_in", "").strip()
        check_out_str = request.POST.get("check_out", "").strip()
        is_late = request.POST.get("is_late") == "on"
        is_early_checkout = request.POST.get("is_early_checkout") == "on"
        notes = request.POST.get("notes", "").strip()

        try:
            emp = EmployeeProfile.objects.get(pk=emp_id)
            rec_date = dt.strptime(date_str, "%Y-%m-%d").date()
            check_in = dt.strptime(check_in_str, "%H:%M").time() if check_in_str else None
            check_out = dt.strptime(check_out_str, "%H:%M").time() if check_out_str else None

            if record:
                record.employee = emp
                record.date = rec_date
                record.status = status
                record.check_in = check_in
                record.check_out = check_out
                record.is_late = is_late
                record.is_early_checkout = is_early_checkout
                record.notes = notes
                record.save()
                messages.success(request, f"Attendance record updated for {emp.full_name}.")
            else:
                AttendanceRecord.objects.update_or_create(
                    employee=emp, date=rec_date,
                    defaults={
                        "status": status,
                        "check_in": check_in,
                        "check_out": check_out,
                        "is_late": is_late,
                        "is_early_checkout": is_early_checkout,
                        "notes": notes,
                    }
                )
                messages.success(request, f"Attendance record saved for {emp.full_name}.")
            return redirect(f"/portal/hr/attendance/?year={rec_date.year}&month={rec_date.month}")
        except (EmployeeProfile.DoesNotExist, ValueError) as e:
            errors["general"] = str(e)

    return render(request, "portal/hr/attendance_record_form.html", {
        "record": record,
        "all_employees": all_employees,
        "status_choices": AttendanceRecord.StatusChoices.choices,
        "errors": errors,
        "today": timezone.localdate(),
    })


@login_required(login_url="/portal/login/")
def hr_attendance_record_delete(request, pk):
    if not _hr_check(request):
        return redirect("portal:dashboard")
    record = get_object_or_404(AttendanceRecord, pk=pk)
    if request.method == "POST":
        rec_date = record.date
        emp_name = record.employee.full_name
        record.delete()
        messages.success(request, f"Record for {emp_name} on {rec_date} deleted.")
        return redirect(f"/portal/hr/attendance/?year={rec_date.year}&month={rec_date.month}")
    return render(request, "portal/hr/confirm_delete.html", {
        "title": "Delete Attendance Record",
        "description": f"{record.employee.full_name} â€” {record.date} â€” {record.get_status_display()}",
        "back_url": "/portal/hr/attendance/",
    })


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# HR â€” Public Holidays CRUD
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@login_required(login_url="/portal/login/")
def hr_holidays(request):
    if not _hr_check(request):
        return redirect("portal:dashboard")
    holidays = PublicHoliday.objects.order_by("-start_date")
    return render(request, "portal/hr/holidays.html", {"holidays": holidays})


@login_required(login_url="/portal/login/")
def hr_holiday_edit(request, pk=None):
    if not _hr_check(request):
        return redirect("portal:dashboard")
    from datetime import datetime as dt
    holiday = get_object_or_404(PublicHoliday, pk=pk) if pk else None
    errors = {}

    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        start_str = request.POST.get("start_date", "").strip()
        end_str = request.POST.get("end_date", "").strip()
        description = request.POST.get("description", "").strip()
        is_active = request.POST.get("is_active") == "on"
        if not name:
            errors["name"] = "Name is required."
        if not start_str:
            errors["start_date"] = "Start date is required."
        if not errors:
            try:
                start_date = dt.strptime(start_str, "%Y-%m-%d").date()
                end_date = dt.strptime(end_str, "%Y-%m-%d").date() if end_str else None
                if end_date and end_date < start_date:
                    errors["end_date"] = "End date cannot be before start date."
                else:
                    if holiday:
                        holiday.name = name
                        holiday.start_date = start_date
                        holiday.end_date = end_date
                        holiday.description = description
                        holiday.is_active = is_active
                        holiday.save()
                        messages.success(request, "Holiday updated.")
                    else:
                        PublicHoliday.objects.create(
                            name=name, start_date=start_date, end_date=end_date,
                            description=description, is_active=is_active,
                        )
                        messages.success(request, "Holiday added.")
                    return redirect("portal:hr_holidays")
            except ValueError:
                errors["start_date"] = "Invalid date format."

    return render(request, "portal/hr/holiday_form.html", {"holiday": holiday, "errors": errors})


@login_required(login_url="/portal/login/")
def hr_holiday_delete(request, pk):
    if not _hr_check(request):
        return redirect("portal:dashboard")
    holiday = get_object_or_404(PublicHoliday, pk=pk)
    if request.method == "POST":
        holiday.delete()
        messages.success(request, "Holiday deleted.")
        return redirect("portal:hr_holidays")
    return render(request, "portal/hr/confirm_delete.html", {
        "title": "Delete Holiday",
        "description": f"{holiday.name} â€” {holiday.display_date}",
        "back_url": "/portal/hr/attendance/holidays/",
    })


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# HR â€” Shifts CRUD
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@login_required(login_url="/portal/login/")
def hr_shifts(request):
    if not _hr_check(request):
        return redirect("portal:dashboard")
    from attendance.models import Shift
    shifts = Shift.objects.order_by("start_time")
    return render(request, "portal/hr/shifts.html", {"shifts": shifts})


@login_required(login_url="/portal/login/")
def hr_shift_edit(request, pk=None):
    if not _hr_check(request):
        return redirect("portal:dashboard")
    from attendance.models import Shift
    from datetime import datetime as dt
    shift = get_object_or_404(Shift, pk=pk) if pk else None
    errors = {}

    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        start_str = request.POST.get("start_time", "").strip()
        end_str = request.POST.get("end_time", "").strip()
        is_active = request.POST.get("is_active") == "on"
        if not name:
            errors["name"] = "Name is required."
        if not start_str:
            errors["start_time"] = "Required."
        if not end_str:
            errors["end_time"] = "Required."
        if not errors:
            try:
                start_time = dt.strptime(start_str, "%H:%M").time()
                end_time = dt.strptime(end_str, "%H:%M").time()
                if shift:
                    shift.name = name
                    shift.start_time = start_time
                    shift.end_time = end_time
                    shift.is_active = is_active
                    shift.save()
                    messages.success(request, "Shift updated.")
                else:
                    Shift.objects.create(
                        name=name, start_time=start_time, end_time=end_time, is_active=is_active
                    )
                    messages.success(request, "Shift created.")
                return redirect("portal:hr_shifts")
            except ValueError:
                errors["time"] = "Invalid time format."

    return render(request, "portal/hr/shift_form.html", {"shift": shift, "errors": errors})


@login_required(login_url="/portal/login/")
def hr_shift_delete(request, pk):
    if not _hr_check(request):
        return redirect("portal:dashboard")
    from attendance.models import Shift
    shift = get_object_or_404(Shift, pk=pk)
    if request.method == "POST":
        shift.delete()
        messages.success(request, "Shift deleted.")
        return redirect("portal:hr_shifts")
    return render(request, "portal/hr/confirm_delete.html", {
        "title": "Delete Shift",
        "description": f"{shift.name}",
        "back_url": "/portal/hr/attendance/shifts/",
    })


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# HR â€” Payroll Actions
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@login_required(login_url="/portal/login/")
def hr_payroll_create(request):
    if not _hr_check(request):
        return redirect("portal:dashboard")
    from salary.models import PayrollRun
    errors = {}

    if request.method == "POST":
        try:
            year = int(request.POST.get("year", 0))
            month = int(request.POST.get("month", 0))
            notes = request.POST.get("notes", "").strip()
            if not (1 <= month <= 12):
                errors["month"] = "Select a valid month."
            elif PayrollRun.objects.filter(year=year, month=month).exists():
                errors["general"] = f"A payroll run for {calendar.month_name[month]} {year} already exists."
            else:
                run = PayrollRun.objects.create(year=year, month=month, notes=notes)
                messages.success(request, f"Payroll run created for {run}.")
                return redirect("portal:hr_payroll_detail", pk=run.pk)
        except (ValueError, TypeError):
            errors["general"] = "Invalid year or month."

    today = timezone.localdate()
    months = [(i, calendar.month_name[i]) for i in range(1, 13)]
    return render(request, "portal/hr/payroll_create.html", {
        "errors": errors, "today": today, "months": months,
        "current_year": today.year, "current_month": today.month,
    })


@login_required(login_url="/portal/login/")
def hr_payroll_generate(request, pk):
    if not _hr_check(request):
        return redirect("portal:dashboard")
    if request.method != "POST":
        return redirect("portal:hr_payroll_detail", pk=pk)
    from salary.models import PayrollRun
    from salary.services import generate_payslips
    run = get_object_or_404(PayrollRun, pk=pk)
    if run.status == PayrollRun.StatusChoices.LOCKED:
        messages.error(request, "Cannot regenerate payslips for a locked run.")
    else:
        count = generate_payslips(run, created_by=request.user)
        messages.success(request, f"Generated {count} payslip(s) for {run}.")
    return redirect("portal:hr_payroll_detail", pk=pk)


@login_required(login_url="/portal/login/")
def hr_payroll_finalize(request, pk):
    if not _hr_check(request):
        return redirect("portal:dashboard")
    if request.method != "POST":
        return redirect("portal:hr_payroll_detail", pk=pk)
    from salary.models import PayrollRun, Payslip
    run = get_object_or_404(PayrollRun, pk=pk)
    if run.status == PayrollRun.StatusChoices.LOCKED:
        messages.error(request, "Run is already locked.")
    else:
        updated = run.payslips.filter(status=Payslip.StatusChoices.DRAFT).update(
            status=Payslip.StatusChoices.FINALIZED
        )
        run.status = PayrollRun.StatusChoices.APPROVED
        run.save()
        messages.success(request, f"Finalized {updated} payslip(s). Run is now Approved.")
    return redirect("portal:hr_payroll_detail", pk=pk)


@login_required(login_url="/portal/login/")
def hr_payroll_lock(request, pk):
    if not _hr_check(request):
        return redirect("portal:dashboard")
    if request.method != "POST":
        return redirect("portal:hr_payroll_detail", pk=pk)
    from salary.models import PayrollRun
    run = get_object_or_404(PayrollRun, pk=pk)
    if run.status == PayrollRun.StatusChoices.LOCKED:
        messages.warning(request, "Run is already locked.")
    else:
        run.status = PayrollRun.StatusChoices.LOCKED
        run.save()
        messages.success(request, f"Payroll run locked. No further edits allowed.")
    return redirect("portal:hr_payroll_detail", pk=pk)


@login_required(login_url="/portal/login/")
def hr_payslip_edit(request, pk):
    if not _hr_check(request):
        return redirect("portal:dashboard")
    from salary.models import Payslip, PayrollRun
    from decimal import Decimal, InvalidOperation
    payslip = get_object_or_404(Payslip, pk=pk)
    if payslip.payroll_run.status == PayrollRun.StatusChoices.LOCKED:
        messages.error(request, "Cannot edit a payslip in a locked run.")
        return redirect("portal:hr_payroll_detail", pk=payslip.payroll_run.pk)

    errors = {}
    if request.method == "POST":
        def dec(field, default="0"):
            return Decimal(request.POST.get(field, default) or default)

        try:
            payslip.gross_salary = dec("gross_salary")
            payslip.bonus = dec("bonus")
            payslip.overtime_hours = dec("overtime_hours")
            payslip.overtime_rate = dec("overtime_rate")
            payslip.adjustment_addition = dec("adjustment_addition")
            payslip.adjustment_deduction = dec("adjustment_deduction")
            payslip.income_tax = dec("income_tax")
            payslip.eobi = dec("eobi")
            payslip.provident_fund = dec("provident_fund")
            payslip.unpaid_leave_deduction = dec("unpaid_leave_deduction")
            payslip.total_deductions = dec("total_deductions")
            payslip.net_salary = dec("net_salary")
            payslip.is_paid = "is_paid" in request.POST
            payslip.status = request.POST.get("status", payslip.status)
            payslip.save()
            messages.success(request, f"Payslip for {payslip.employee.full_name} updated.")
            return redirect("portal:hr_payroll_detail", pk=payslip.payroll_run.pk)
        except (InvalidOperation, ValueError) as e:
            errors["general"] = f"Invalid value: {e}"

    return render(request, "portal/hr/payslip_edit.html", {
        "payslip": payslip, "run": payslip.payroll_run,
        "errors": errors, "status_choices": Payslip.StatusChoices.choices,
    })


# â”€â”€â”€ SALARY SETUPS â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@login_required
def hr_salary_setups(request):
    if not _hr_check(request):
        return redirect("portal:dashboard")
    from salary.models import SalarySetup
    from accounts.models import EmployeeProfile
    q = request.GET.get("q", "").strip()
    qs = SalarySetup.objects.select_related("employee").order_by("employee__full_name")
    if q:
        qs = qs.filter(employee__full_name__icontains=q)
    return render(request, "portal/hr/salary_setups.html", {"setups": qs, "q": q})


@login_required
def hr_salary_setup_edit(request, pk=None):
    if not _hr_check(request):
        return redirect("portal:dashboard")
    from salary.models import SalarySetup
    from accounts.models import EmployeeProfile
    from decimal import Decimal, InvalidOperation
    setup = get_object_or_404(SalarySetup, pk=pk) if pk else None
    all_employees = EmployeeProfile.objects.filter(employment_status="Active").order_by("full_name")
    errors = {}
    if request.method == "POST":
        def dec(f, default="0"):
            return Decimal(request.POST.get(f, default) or default)
        try:
            if not setup:
                emp_pk = request.POST.get("employee")
                emp = get_object_or_404(EmployeeProfile, pk=emp_pk)
                setup = SalarySetup(employee=emp)
            from salary.services import q as salary_q
            gross = dec("gross_salary_input")
            setup.gross_salary_input = gross
            # Auto-distribute from gross if component fields weren't manually overridden
            setup.basic_salary          = dec("basic_salary") or salary_q(gross * Decimal("0.60"))
            setup.house_rent_allowance  = dec("house_rent_allowance") or salary_q(gross * Decimal("0.20"))
            setup.utility_allowance     = dec("utility_allowance") or salary_q(gross * Decimal("0.10"))
            setup.medical_allowance     = dec("medical_allowance") or salary_q(gross * Decimal("0.10"))
            setup.conveyance_allowance  = dec("conveyance_allowance")
            setup.other_allowance       = dec("other_allowance")
            setup.currency = request.POST.get("currency", "PKR").strip()
            setup.payment_mode = request.POST.get("payment_mode", "Bank").strip()
            setup.bank_name = request.POST.get("bank_name", "").strip()
            setup.account_title = request.POST.get("account_title", "").strip()
            setup.account_number = request.POST.get("account_number", "").strip()
            setup.ntn_no = request.POST.get("ntn_no", "").strip()
            setup.eobi_contribution = dec("eobi_contribution")
            setup.provident_fund_deduction = dec("provident_fund_deduction")
            setup.loan_installment = dec("loan_installment")
            setup.advance_salary_repayment = dec("advance_salary_repayment")
            setup.misc_deduction = dec("misc_deduction")
            setup.notes = request.POST.get("notes", "").strip()
            setup.is_active = "is_active" in request.POST
            setup.save()
            messages.success(request, "Salary setup saved.")
            return redirect("portal:hr_salary_setups")
        except (InvalidOperation, ValueError) as e:
            errors["general"] = f"Invalid value: {e}"
    return render(request, "portal/hr/salary_setup_form.html", {
        "setup": setup, "all_employees": all_employees, "errors": errors,
        "payment_modes": [("Bank", "Bank"), ("Cash", "Cash")],
    })


@login_required
def hr_salary_calculate(request):
    """AJAX: return breakdown given a gross salary."""
    if not _hr_check(request):
        return JsonResponse({"error": "Forbidden"}, status=403)
    from decimal import Decimal, InvalidOperation
    from salary.services import calculate_monthly_tax, q
    try:
        gross = Decimal(request.GET.get("gross", "0") or "0")
    except InvalidOperation:
        return JsonResponse({"error": "Invalid gross salary"}, status=400)
    if gross <= 0:
        zero = "0.00"
        return JsonResponse({k: zero for k in [
            "basic_salary", "house_rent_allowance", "utility_allowance",
            "medical_allowance", "monthly_income_tax", "annual_taxable_income",
            "annual_tax", "net_salary",
        ]})
    basic = q(gross * Decimal("0.60"))
    hra   = q(gross * Decimal("0.20"))
    util  = q(gross * Decimal("0.10"))
    # Medical gets the remainder so components always sum exactly to gross
    med   = q(gross - basic - hra - util)
    monthly_taxable = q(gross * Decimal("0.90"))
    annual_taxable  = q(monthly_taxable * Decimal("12"))
    from salary.services import calculate_annual_tax_from_slab
    annual_tax = calculate_annual_tax_from_slab(annual_taxable)
    monthly_tax = q(annual_tax / Decimal("12"))
    net = q(gross - monthly_tax)
    return JsonResponse({
        "basic_salary":           str(basic),
        "house_rent_allowance":   str(hra),
        "utility_allowance":      str(util),
        "medical_allowance":      str(med),
        "monthly_taxable_income": str(monthly_taxable),
        "annual_taxable_income":  str(annual_taxable),
        "annual_tax":             str(annual_tax),
        "monthly_income_tax":     str(monthly_tax),
        "net_salary":             str(net),
    })


@login_required
def hr_salary_setup_delete(request, pk):
    if not _hr_check(request):
        return redirect("portal:dashboard")
    from salary.models import SalarySetup
    setup = get_object_or_404(SalarySetup, pk=pk)
    if request.method == "POST":
        setup.delete()
        messages.success(request, "Salary setup deleted.")
        return redirect("portal:hr_salary_setups")
    return render(request, "portal/hr/confirm_delete.html", {
        "obj": setup, "back_url": "portal:hr_salary_setups",
        "title": f"Delete Salary Setup â€” {setup.employee.full_name}",
    })


# â”€â”€â”€ SALARY FORECAST â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@login_required
def hr_salary_forecast(request):
    if not _hr_check(request):
        return redirect("portal:dashboard")
    from decimal import Decimal
    from salary.models import SalarySetup
    from salary.services import calculate_annual_tax_from_slab, q as salary_q
    import calendar as _cal

    today = timezone.localdate()
    current_year = today.year
    current_month = today.month

    # Gather all active salary setups
    setups = list(SalarySetup.objects.filter(is_active=True).select_related("employee"))

    def monthly_tax(gross):
        taxable = salary_q(gross * Decimal("0.90"))
        annual = taxable * Decimal("12")
        return salary_q(calculate_annual_tax_from_slab(annual) / Decimal("12"))

    def net(gross):
        return salary_q(gross - monthly_tax(gross))

    # Per-employee data
    employees_data = []
    total_gross = Decimal("0")
    total_net = Decimal("0")
    total_tax = Decimal("0")
    for s in setups:
        g = salary_q(s.gross_salary_input or s.gross_salary or Decimal("0"))
        t = monthly_tax(g)
        n = salary_q(g - t)
        total_gross += g
        total_tax += t
        total_net += n
        employees_data.append({
            "name": s.employee.full_name,
            "dept": s.employee.department or "â€”",
            "gross": g,
            "tax": t,
            "net": n,
        })
    employees_data.sort(key=lambda x: x["gross"], reverse=True)

    # Remaining months in current year (including current month)
    remaining_months = 13 - current_month  # months from current to Dec inclusive
    spent_months = current_month - 1       # months already passed (Jan to last month)

    this_year_total_gross = salary_q(total_gross * Decimal(str(12)))
    this_year_paid_gross = salary_q(total_gross * Decimal(str(spent_months)))
    this_year_remaining_gross = salary_q(total_gross * Decimal(str(remaining_months)))

    next_year_total_gross = salary_q(total_gross * Decimal("12"))
    next_year_total_net = salary_q(total_net * Decimal("12"))
    next_year_total_tax = salary_q(total_tax * Decimal("12"))

    # Month-by-month projection for this year (remaining months)
    month_projections = []
    for m in range(current_month, 13):
        month_projections.append({
            "month": _cal.month_name[m],
            "month_num": m,
            "gross": total_gross,
            "tax": total_tax,
            "net": total_net,
        })

    # Next year month-by-month
    next_year_months = []
    for m in range(1, 13):
        next_year_months.append({
            "month": _cal.month_name[m],
            "gross": total_gross,
            "tax": total_tax,
            "net": total_net,
        })

    return render(request, "portal/hr/salary_forecast.html", {
        "employees_data": employees_data,
        "total_gross": total_gross,
        "total_tax": total_tax,
        "total_net": total_net,
        "employee_count": len(setups),
        "this_year_total_gross": this_year_total_gross,
        "this_year_paid_gross": this_year_paid_gross,
        "this_year_remaining_gross": this_year_remaining_gross,
        "next_year_total_gross": next_year_total_gross,
        "next_year_total_net": next_year_total_net,
        "next_year_total_tax": next_year_total_tax,
        "month_projections": month_projections,
        "next_year_months": next_year_months,
        "current_year": current_year,
        "next_year": current_year + 1,
        "current_month_name": _cal.month_name[current_month],
        "spent_months": spent_months,
        "remaining_months": remaining_months,
    })


# â”€â”€â”€ STATUTORY DEDUCTIONS â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@login_required
def hr_statutory_deductions(request):
    if not _hr_check(request):
        return redirect("portal:dashboard")
    from salary.models import StatutoryDeductionPolicy
    items = StatutoryDeductionPolicy.objects.order_by("-effective_from")
    return render(request, "portal/hr/statutory_deductions.html", {"items": items})


@login_required
def hr_statutory_deduction_edit(request, pk=None):
    if not _hr_check(request):
        return redirect("portal:dashboard")
    from salary.models import StatutoryDeductionPolicy
    from decimal import Decimal, InvalidOperation
    obj = get_object_or_404(StatutoryDeductionPolicy, pk=pk) if pk else None
    errors = {}
    if request.method == "POST":
        def dec(f, default="0"):
            return Decimal(request.POST.get(f, default) or default)
        try:
            if not obj:
                obj = StatutoryDeductionPolicy()
            obj.name = request.POST.get("name", "").strip()
            obj.effective_from = request.POST.get("effective_from") or None
            obj.effective_to = request.POST.get("effective_to") or None
            obj.eobi_employee_fixed = dec("eobi_employee_fixed")
            obj.provident_fund_employee_percent = dec("provident_fund_employee_percent")
            obj.provident_fund_employer_percent = dec("provident_fund_employer_percent")
            obj.social_security_fixed = dec("social_security_fixed")
            obj.other_statutory_fixed = dec("other_statutory_fixed")
            obj.is_active = "is_active" in request.POST
            obj.notes = request.POST.get("notes", "").strip()
            obj.save()
            messages.success(request, "Statutory deduction saved.")
            return redirect("portal:hr_statutory_deductions")
        except (InvalidOperation, ValueError) as e:
            errors["general"] = f"Invalid value: {e}"
    return render(request, "portal/hr/statutory_deduction_form.html", {"obj": obj, "errors": errors})


@login_required
def hr_statutory_deduction_delete(request, pk):
    if not _hr_check(request):
        return redirect("portal:dashboard")
    from salary.models import StatutoryDeductionPolicy
    obj = get_object_or_404(StatutoryDeductionPolicy, pk=pk)
    if request.method == "POST":
        obj.delete()
        messages.success(request, "Statutory deduction deleted.")
        return redirect("portal:hr_statutory_deductions")
    return render(request, "portal/hr/confirm_delete.html", {
        "obj": obj, "back_url": "portal:hr_statutory_deductions",
        "title": f"Delete Statutory Deduction â€” {obj.name}",
    })


# â”€â”€â”€ TAX YEARS â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@login_required
def hr_tax_years(request):
    if not _hr_check(request):
        return redirect("portal:dashboard")
    from salary.models import TaxYear
    items = TaxYear.objects.order_by("-effective_from")
    return render(request, "portal/hr/tax_years.html", {"items": items})


@login_required
def hr_tax_year_edit(request, pk=None):
    if not _hr_check(request):
        return redirect("portal:dashboard")
    from salary.models import TaxYear
    obj = get_object_or_404(TaxYear, pk=pk) if pk else None
    errors = {}
    if request.method == "POST":
        try:
            if not obj:
                obj = TaxYear()
            obj.fiscal_year = request.POST.get("fiscal_year", "").strip()
            obj.effective_from = request.POST.get("effective_from") or None
            obj.effective_to = request.POST.get("effective_to") or None
            obj.is_active = "is_active" in request.POST
            obj.notes = request.POST.get("notes", "").strip()
            obj.save()
            messages.success(request, "Tax year saved.")
            return redirect("portal:hr_tax_years")
        except Exception as e:
            errors["general"] = str(e)
    slabs = obj.slabs.order_by("sort_order", "annual_min_income") if obj else []
    return render(request, "portal/hr/tax_year_form.html", {"obj": obj, "errors": errors, "slabs": slabs})


@login_required
def hr_tax_year_delete(request, pk):
    if not _hr_check(request):
        return redirect("portal:dashboard")
    from salary.models import TaxYear
    obj = get_object_or_404(TaxYear, pk=pk)
    if request.method == "POST":
        obj.delete()
        messages.success(request, "Tax year deleted.")
        return redirect("portal:hr_tax_years")
    return render(request, "portal/hr/confirm_delete.html", {
        "obj": obj, "back_url": "portal:hr_tax_years",
        "title": f"Delete Tax Year â€” {obj.fiscal_year}",
    })


@login_required
def hr_tax_slab_inline_add(request, tax_year_pk):
    if not _hr_check(request):
        return JsonResponse({"error": "Forbidden"}, status=403)
    from salary.models import TaxYear, SalaryTaxSlab
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)
    tax_year = get_object_or_404(TaxYear, pk=tax_year_pk)
    try:
        slab = SalaryTaxSlab(
            tax_year=tax_year,
            name=request.POST.get("name", "").strip(),
            annual_min_income=request.POST.get("annual_min_income") or 0,
            annual_max_income=request.POST.get("annual_max_income") or None,
            taxable_excess_over=request.POST.get("taxable_excess_over") or 0,
            base_tax=request.POST.get("base_tax") or 0,
            rate_percent=request.POST.get("rate_percent") or 0,
            sort_order=request.POST.get("sort_order") or 0,
        )
        slab.full_clean()
        slab.save()
        return JsonResponse({
            "id": slab.pk, "name": slab.name,
            "annual_min_income": str(slab.annual_min_income),
            "annual_max_income": str(slab.annual_max_income) if slab.annual_max_income is not None else "",
            "taxable_excess_over": str(slab.taxable_excess_over),
            "base_tax": str(slab.base_tax),
            "rate_percent": str(slab.rate_percent),
            "sort_order": slab.sort_order,
        })
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=400)


@login_required
def hr_tax_slab_inline_update(request, pk):
    if not _hr_check(request):
        return JsonResponse({"error": "Forbidden"}, status=403)
    from salary.models import SalaryTaxSlab
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)
    slab = get_object_or_404(SalaryTaxSlab, pk=pk)
    try:
        slab.name = request.POST.get("name", slab.name).strip()
        slab.annual_min_income = request.POST.get("annual_min_income") or 0
        raw_max = request.POST.get("annual_max_income", "").strip()
        slab.annual_max_income = raw_max if raw_max else None
        slab.taxable_excess_over = request.POST.get("taxable_excess_over") or 0
        slab.base_tax = request.POST.get("base_tax") or 0
        slab.rate_percent = request.POST.get("rate_percent") or 0
        slab.sort_order = request.POST.get("sort_order") or 0
        slab.full_clean()
        slab.save()
        return JsonResponse({"ok": True})
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=400)


@login_required
def hr_tax_slab_inline_delete(request, pk):
    if not _hr_check(request):
        return JsonResponse({"error": "Forbidden"}, status=403)
    from salary.models import SalaryTaxSlab
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)
    slab = get_object_or_404(SalaryTaxSlab, pk=pk)
    slab.delete()
    return JsonResponse({"ok": True})


# â”€â”€â”€ ATTENDANCE POLICY â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@login_required
def hr_attendance_policy(request):
    if not _hr_check(request):
        return redirect("portal:dashboard")
    from attendance.models import AttendancePolicy
    obj, _ = AttendancePolicy.objects.get_or_create(pk=1)
    errors = {}
    if request.method == "POST":
        try:
            obj.checkin_buffer_minutes = int(request.POST.get("checkin_buffer_minutes", 0))
            obj.checkout_buffer_minutes = int(request.POST.get("checkout_buffer_minutes", 0))
            obj.save()
            messages.success(request, "Attendance policy updated.")
            return redirect("portal:hr_attendance_policy")
        except Exception as e:
            errors["general"] = str(e)
    return render(request, "portal/hr/attendance_policy.html", {"obj": obj, "errors": errors})


# â”€â”€â”€ DEVICE EMPLOYEES â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@login_required
def hr_device_employees(request):
    if not _hr_check(request):
        return redirect("portal:dashboard")
    from attendance.models import DeviceEmployee
    items = DeviceEmployee.objects.select_related("employee").order_by("employee__full_name")
    return render(request, "portal/hr/device_employees.html", {"items": items})


@login_required
def hr_device_employee_edit(request, pk=None):
    if not _hr_check(request):
        return redirect("portal:dashboard")
    from attendance.models import DeviceEmployee
    from accounts.models import EmployeeProfile
    obj = get_object_or_404(DeviceEmployee, pk=pk) if pk else None
    all_employees = EmployeeProfile.objects.order_by("full_name")
    errors = {}
    if request.method == "POST":
        try:
            emp_pk = request.POST.get("employee")
            emp = get_object_or_404(EmployeeProfile, pk=emp_pk)
            device_user_id = int(request.POST.get("device_user_id", 0))
            if not obj:
                obj = DeviceEmployee(employee=emp)
            obj.employee = emp
            obj.device_user_id = device_user_id
            obj.save()
            messages.success(request, "Device employee saved.")
            return redirect("portal:hr_device_employees")
        except Exception as e:
            errors["general"] = str(e)
    return render(request, "portal/hr/device_employee_form.html", {
        "obj": obj, "all_employees": all_employees, "errors": errors,
    })


@login_required
def hr_device_employee_delete(request, pk):
    if not _hr_check(request):
        return redirect("portal:dashboard")
    from attendance.models import DeviceEmployee
    obj = get_object_or_404(DeviceEmployee, pk=pk)
    if request.method == "POST":
        obj.delete()
        messages.success(request, "Device employee deleted.")
        return redirect("portal:hr_device_employees")
    return render(request, "portal/hr/confirm_delete.html", {
        "obj": obj, "back_url": "portal:hr_device_employees",
        "title": f"Delete Device Employee â€” {obj.employee.full_name}",
    })


# â”€â”€â”€ SYNC SCHEDULES â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@login_required
def hr_sync_schedules(request):
    if not _hr_check(request):
        return redirect("portal:dashboard")
    from attendance.models import SyncSchedule
    items = SyncSchedule.objects.order_by("sync_time_1")
    return render(request, "portal/hr/sync_schedules.html", {"items": items})


@login_required
def hr_sync_schedule_edit(request, pk=None):
    if not _hr_check(request):
        return redirect("portal:dashboard")
    from attendance.models import SyncSchedule
    obj = get_object_or_404(SyncSchedule, pk=pk) if pk else None
    errors = {}
    if request.method == "POST":
        try:
            if not obj:
                obj = SyncSchedule()
            obj.sync_time_1 = request.POST.get("sync_time_1") or None
            obj.sync_time_2 = request.POST.get("sync_time_2") or None
            obj.is_active = "is_active" in request.POST
            obj.save()
            messages.success(request, "Sync schedule saved.")
            return redirect("portal:hr_sync_schedules")
        except Exception as e:
            errors["general"] = str(e)
    return render(request, "portal/hr/sync_schedule_form.html", {"obj": obj, "errors": errors})


@login_required
def hr_sync_schedule_delete(request, pk):
    if not _hr_check(request):
        return redirect("portal:dashboard")
    from attendance.models import SyncSchedule
    obj = get_object_or_404(SyncSchedule, pk=pk)
    if request.method == "POST":
        obj.delete()
        messages.success(request, "Sync schedule deleted.")
        return redirect("portal:hr_sync_schedules")
    return render(request, "portal/hr/confirm_delete.html", {
        "obj": obj, "back_url": "portal:hr_sync_schedules",
        "title": "Delete Sync Schedule",
    })


@login_required
def hr_sync_schedule_fetch(request):
    if not _hr_check(request):
        return redirect("portal:dashboard")

    from attendance.views import force_adms_data_query
    import socket

    cfg = getattr(settings, "ZK_DEVICE", {})
    host = cfg.get("host")
    port = cfg.get("port", 4370)

    if not host:
        messages.error(
            request,
            "No biometric device configured. Set ZK_DEVICE['host'] in settings.py."
        )
        return redirect("portal:hr_sync_schedules")

    # Quick TCP probe (3 s) to decide pull-mode vs push-mode
    tcp_reachable = False
    try:
        with socket.create_connection((host, port), timeout=3):
            tcp_reachable = True
    except Exception:
        tcp_reachable = False

    if tcp_reachable:
        # Pull mode: connect with pyzk and fetch logs directly
        output = StringIO()
        try:
            call_command("sync_device_attendance", stdout=output)
            raw_out = output.getvalue().strip()
            last_line = raw_out.splitlines()[-1] if raw_out else "Attendance sync completed."
            messages.success(request, f"âœ“ {last_line}")
        except CommandError as exc:
            messages.error(request, f"Sync error: {exc}")
        except Exception as exc:
            messages.error(request, f"Unexpected error during sync: {exc}")
    else:
        # Push mode: signal the device to resend its logs on next ADMS poll.
        # This is the normal path for cloud-hosted servers â€” the device IP is
        # a private LAN address not reachable from the internet.
        force_adms_data_query()
        messages.success(
            request,
            "âœ“ DATA QUERY queued. The biometric device will push its latest logs "
            "on its next heartbeat poll (within 1 minute). "
            "This is normal â€” the device is on your office LAN and pushes to the server, "
            "not the other way around."
        )

    return redirect("portal:hr_sync_schedules")


# â”€â”€â”€ LEAVE TYPES â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@login_required
def hr_leave_types(request):
    if not _hr_check(request):
        return redirect("portal:dashboard")
    from leaves.models import LeaveType
    items = LeaveType.objects.order_by("name")
    return render(request, "portal/hr/leave_types.html", {"items": items})


@login_required
def hr_leave_type_edit(request, pk=None):
    if not _hr_check(request):
        return redirect("portal:dashboard")
    from leaves.models import LeaveType
    from decimal import Decimal, InvalidOperation
    obj = get_object_or_404(LeaveType, pk=pk) if pk else None
    errors = {}
    if request.method == "POST":
        try:
            if not obj:
                obj = LeaveType()
            obj.name = request.POST.get("name", "").strip()
            obj.is_paid = "is_paid" in request.POST
            obj.default_days = Decimal(request.POST.get("default_days", "0") or "0")
            obj.requires_attachment = "requires_attachment" in request.POST
            obj.available_for_probation = "available_for_probation" in request.POST
            obj.is_active = "is_active" in request.POST
            obj.save()
            messages.success(request, "Leave type saved.")
            return redirect("portal:hr_leave_types")
        except Exception as e:
            errors["general"] = str(e)
    return render(request, "portal/hr/leave_type_form.html", {"obj": obj, "errors": errors})


@login_required
def hr_leave_type_delete(request, pk):
    if not _hr_check(request):
        return redirect("portal:dashboard")
    from leaves.models import LeaveType
    obj = get_object_or_404(LeaveType, pk=pk)
    if request.method == "POST":
        obj.delete()
        messages.success(request, "Leave type deleted.")
        return redirect("portal:hr_leave_types")
    return render(request, "portal/hr/confirm_delete.html", {
        "obj": obj, "back_url": "portal:hr_leave_types",
        "title": f"Delete Leave Type â€” {obj.name}",
    })


# â”€â”€â”€ LEAVE ALLOCATIONS â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@login_required
def hr_leave_allocations(request):
    if not _hr_check(request):
        return redirect("portal:dashboard")
    from leaves.models import LeaveAllocation, LeaveType
    from accounts.models import EmployeeProfile
    q = request.GET.get("q", "").strip()
    year = request.GET.get("year", "")
    qs = LeaveAllocation.objects.select_related("employee", "leave_type").order_by("-year", "employee__full_name")
    if q:
        qs = qs.filter(employee__full_name__icontains=q)
    if year:
        qs = qs.filter(year=year)
    years = LeaveAllocation.objects.values_list("year", flat=True).distinct().order_by("-year")
    return render(request, "portal/hr/leave_allocations.html", {
        "items": qs, "q": q, "year": year, "years": years,
    })


@login_required
def hr_leave_allocation_edit(request, pk=None):
    if not _hr_check(request):
        return redirect("portal:dashboard")
    from leaves.models import LeaveAllocation, LeaveType
    from accounts.models import EmployeeProfile
    from decimal import Decimal, InvalidOperation
    obj = get_object_or_404(LeaveAllocation, pk=pk) if pk else None
    all_employees = EmployeeProfile.objects.filter(employment_status="Active").order_by("full_name")
    all_types = LeaveType.objects.filter(is_active=True).order_by("name")
    errors = {}
    if request.method == "POST":
        try:
            emp_pk = request.POST.get("employee")
            lt_pk = request.POST.get("leave_type")
            emp = get_object_or_404(EmployeeProfile, pk=emp_pk)
            lt = get_object_or_404(LeaveType, pk=lt_pk)
            if not obj:
                obj = LeaveAllocation(employee=emp, leave_type=lt)
            obj.employee = emp
            obj.leave_type = lt
            obj.year = int(request.POST.get("year", 2025))
            obj.allocated_days = Decimal(request.POST.get("allocated_days", "0") or "0")
            obj.carry_forward_days = Decimal(request.POST.get("carry_forward_days", "0") or "0")
            obj.notes = request.POST.get("notes", "").strip()
            obj.save()
            messages.success(request, "Leave allocation saved.")
            return redirect("portal:hr_leave_allocations")
        except Exception as e:
            errors["general"] = str(e)
    import datetime
    current_year = datetime.date.today().year
    return render(request, "portal/hr/leave_allocation_form.html", {
        "obj": obj, "all_employees": all_employees, "all_types": all_types,
        "errors": errors, "current_year": current_year,
    })


@login_required
def hr_leave_allocation_delete(request, pk):
    if not _hr_check(request):
        return redirect("portal:dashboard")
    from leaves.models import LeaveAllocation
    obj = get_object_or_404(LeaveAllocation, pk=pk)
    if request.method == "POST":
        obj.delete()
        messages.success(request, "Leave allocation deleted.")
        return redirect("portal:hr_leave_allocations")
    return render(request, "portal/hr/confirm_delete.html", {
        "obj": obj, "back_url": "portal:hr_leave_allocations",
        "title": f"Delete Allocation â€” {obj.employee.full_name} / {obj.leave_type.name}",
    })


# â”€â”€â”€ WFH â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

# â”€â”€â”€ Short Leave HR views â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@login_required
def hr_short_leaves(request):
    """HR: view and action all short leave requests."""
    if not _hr_check(request):
        return redirect("portal:dashboard")
    from leaves.models import ShortLeaveRequest as SLR
    from attendance.models import AttendanceRecord
    from attendance.services import sync_leave_request_to_attendance

    tab = request.GET.get("tab", "pending")
    q = request.GET.get("q", "").strip()

    status_map = {
        "pending":          SLR.StatusChoices.PENDING,
        "manager_approved": SLR.StatusChoices.MANAGER_APPROVED,
        "approved":         SLR.StatusChoices.APPROVED,
        "rejected":         SLR.StatusChoices.REJECTED,
    }
    counts = {k: SLR.objects.filter(status=v).count() for k, v in status_map.items()}
    qs = SLR.objects.filter(status=status_map.get(tab, SLR.StatusChoices.PENDING)).select_related(
        "employee", "approved_by", "manager_approved_by"
    ).order_by("-date")
    if q:
        from django.db.models import Q as DjQ
        qs = qs.filter(DjQ(employee__full_name__icontains=q) | DjQ(employee__employee_code__icontains=q))

    return render(request, "portal/hr/short_leaves.html", {
        "items": list(qs), "tab": tab, "counts": counts, "q": q,
    })


@login_required
def hr_short_leave_action(request, pk):
    """HR: approve / reject a short leave request."""
    if not _hr_check(request):
        return redirect("portal:dashboard")
    if request.method != "POST":
        return redirect("portal:hr_short_leaves")

    from leaves.models import ShortLeaveRequest as SLR
    sl = get_object_or_404(SLR, pk=pk)
    profile = getattr(request.user, "employee_profile", None)
    action  = request.POST.get("action")
    remarks = request.POST.get("remarks", "").strip()
    next_tab = request.POST.get("next_tab", "pending")

    if action == "approve":
        sl.status = SLR.StatusChoices.APPROVED
        sl.approved_by = profile
        if remarks: sl.remarks = remarks
        sl.save()
        # Mark attendance as half_day
        from attendance.models import AttendanceRecord
        AttendanceRecord.objects.update_or_create(
            employee=sl.employee, date=sl.date,
            defaults={"status": AttendanceRecord.StatusChoices.HALF_DAY, "notes": f"Short leave ({sl.period})"},
        )
        messages.success(request, f"Short leave approved for {sl.employee.full_name}.")
    elif action == "reject":
        sl.status = SLR.StatusChoices.REJECTED
        if remarks: sl.remarks = remarks
        sl.save()
        messages.warning(request, f"Short leave rejected for {sl.employee.full_name}.")

    return redirect(f"/portal/hr/short-leaves/?tab={next_tab}")


@login_required
def hr_short_leave_policy(request):
    """HR: configure short leave policy."""
    if not _hr_check(request):
        return redirect("portal:dashboard")
    from leaves.models import ShortLeavePolicy
    from decimal import Decimal, InvalidOperation

    policy = ShortLeavePolicy.get()
    errors = {}

    if request.method == "POST":
        try:
            def _int(name, default):
                try: return max(0, int(request.POST.get(name, default) or default))
                except (ValueError, TypeError): return default
            def _dec(name, default):
                try: return Decimal(request.POST.get(name, str(default)) or str(default))
                except InvalidOperation: return Decimal(str(default))

            policy.is_enabled             = "is_enabled" in request.POST
            policy.max_per_month          = _int("max_per_month", 2)
            policy.min_hours_before_afternoon = _dec("min_hours_before_afternoon", 4)
            policy.notes                  = request.POST.get("notes", "").strip()
            policy.save()
            messages.success(request, "Short leave policy updated.")
            return redirect("portal:hr_short_leave_policy")
        except Exception as e:
            errors["general"] = str(e)

    return render(request, "portal/hr/short_leave_policy.html", {"policy": policy, "errors": errors})


@login_required
def hr_wfh_policy(request):
    """HR: edit the company WFH policy (singleton)."""
    if not _hr_check(request):
        return redirect("portal:dashboard")
    from leaves.models import WFHPolicy
    from decimal import Decimal, InvalidOperation

    policy = WFHPolicy.get()
    errors = {}

    if request.method == "POST":
        try:
            def dec(name, default):
                try:
                    return Decimal(request.POST.get(name, str(default)) or str(default))
                except InvalidOperation:
                    return Decimal(str(default))

            policy.is_enabled = "is_enabled" in request.POST
            policy.monthly_accrual_days = dec("monthly_accrual_days", 2)
            policy.max_balance = dec("max_balance", 5)
            policy.rollover_enabled = "rollover_enabled" in request.POST
            policy.max_days_per_request = dec("max_days_per_request", 5)
            policy.notes = request.POST.get("notes", "").strip()
            policy.full_clean()
            policy.save()
            messages.success(request, "WFH policy updated successfully.")
            return redirect("portal:hr_wfh_policy")
        except Exception as e:
            errors["general"] = str(e)

    return render(request, "portal/hr/wfh_policy.html", {"policy": policy, "errors": errors})


@login_required
def hr_wfh_days(request):
    """HR: manage company-wide WFH days."""
    if not _hr_check(request):
        return redirect("portal:dashboard")
    from attendance.models import CompanyWFHDay
    errors = {}

    if request.method == "POST":
        try:
            from datetime import date as _date, datetime as _dt
            start_str = request.POST.get("start_date", "").strip()
            end_str = request.POST.get("end_date", "").strip()
            title = request.POST.get("title", "Company WFH Day").strip() or "Company WFH Day"
            description = request.POST.get("description", "").strip()
            if not start_str:
                raise ValueError("Start date is required.")
            start_date = _dt.strptime(start_str, "%Y-%m-%d").date()
            end_date = _dt.strptime(end_str, "%Y-%m-%d").date() if end_str else None
            if end_date and end_date < start_date:
                raise ValueError("End date cannot be before start date.")
            CompanyWFHDay.objects.create(
                start_date=start_date, end_date=end_date,
                title=title, description=description,
                declared_by=request.user, is_active=True,
            )
            label = start_date.strftime("%d %b %Y")
            if end_date and end_date != start_date:
                label += f" â€“ {end_date.strftime('%d %b %Y')}"
            messages.success(request, f"Company WFH declared: {label}.")
            return redirect("portal:hr_wfh_days")
        except Exception as e:
            errors["general"] = str(e)

    items = CompanyWFHDay.objects.select_related("declared_by").order_by("-start_date")
    return render(request, "portal/hr/wfh_days.html", {"items": items, "errors": errors})


@login_required
def hr_wfh_day_delete(request, pk):
    if not _hr_check(request):
        return redirect("portal:dashboard")
    from attendance.models import CompanyWFHDay
    obj = get_object_or_404(CompanyWFHDay, pk=pk)
    if request.method == "POST":
        obj.delete()
        messages.success(request, "Company WFH day removed.")
        return redirect("portal:hr_wfh_days")
    return render(request, "portal/hr/confirm_delete.html", {
        "obj": obj, "back_url": "portal:hr_wfh_days",
        "title": f"Remove Company WFH Day â€” {obj.date.strftime('%d %b %Y')}",
    })


@login_required
def hr_wfh_balances(request):
    """HR: view and manage employee WFH balances, run accrual."""
    if not _hr_check(request):
        return redirect("portal:dashboard")
    from leaves.models import WFHBalance
    from accounts.models import EmployeeProfile

    # Trigger manual accrual for all if requested
    if request.method == "POST" and request.POST.get("action") == "accrue_all":
        active_employees = EmployeeProfile.objects.filter(employment_status="Active")
        accrued = 0
        for emp in active_employees:
            bal, _ = WFHBalance.objects.get_or_create(employee=emp)
            bal.accrue()
            accrued += 1
        messages.success(request, f"WFH accrual run for {accrued} active employees.")
        return redirect("portal:hr_wfh_balances")

    # Ensure all active employees have a WFHBalance and are accrued
    active_employees = EmployeeProfile.objects.filter(employment_status="Active").order_by("full_name")
    balances = []
    for emp in active_employees:
        bal, _ = WFHBalance.objects.get_or_create(employee=emp)
        bal.accrue()
        balances.append(bal)

    from leaves.models import WFHPolicy
    policy = WFHPolicy.get()
    return render(request, "portal/hr/wfh_balances.html", {"balances": balances, "policy": policy})


@login_required
def hr_wfh_balance_edit(request, employee_pk):
    """HR: manually adjust a single employee's WFH balance."""
    if not _hr_check(request):
        return redirect("portal:dashboard")
    from leaves.models import WFHBalance, WFHPolicy
    from accounts.models import EmployeeProfile
    from decimal import Decimal, InvalidOperation

    emp = get_object_or_404(EmployeeProfile, pk=employee_pk)
    bal, _ = WFHBalance.objects.get_or_create(employee=emp)
    bal.accrue()
    policy = WFHPolicy.get()
    errors = {}

    if request.method == "POST":
        try:
            action = request.POST.get("action", "set")
            try:
                amount = Decimal(request.POST.get("amount", "0") or "0")
            except InvalidOperation:
                raise ValueError("Enter a valid number.")
            if amount < 0:
                raise ValueError("Amount cannot be negative.")

            if action == "set":
                if amount > policy.max_balance * 2:  # allow admin to override cap but warn
                    pass  # no hard block for admin
                bal.balance = amount
                bal.save(update_fields=["balance", "updated_at"])
                messages.success(request, f"WFH balance for {emp.full_name} set to {amount} days.")
            elif action == "add":
                bal.balance = bal.balance + amount
                bal.save(update_fields=["balance", "updated_at"])
                messages.success(request, f"Added {amount} WFH days to {emp.full_name}. New balance: {bal.balance}.")
            elif action == "subtract":
                bal.balance = max(Decimal("0"), bal.balance - amount)
                bal.save(update_fields=["balance", "updated_at"])
                messages.success(request, f"Subtracted {amount} WFH days from {emp.full_name}. New balance: {bal.balance}.")
            return redirect("portal:hr_wfh_balances")
        except Exception as e:
            errors["general"] = str(e)

    return render(request, "portal/hr/wfh_balance_edit.html", {
        "emp": emp,
        "bal": bal,
        "policy": policy,
        "errors": errors,
    })


# â”€â”€â”€ TEAMS â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@login_required
def hr_teams(request):
    if not _hr_check(request):
        return redirect("portal:dashboard")
    from teams.models import Team
    items = Team.objects.select_related("manager").order_by("name")
    return render(request, "portal/hr/teams.html", {"items": items})


@login_required
def hr_team_edit(request, pk=None):
    if not _hr_check(request):
        return redirect("portal:dashboard")
    from teams.models import Team, TeamMember
    from accounts.models import EmployeeProfile
    obj = get_object_or_404(Team, pk=pk) if pk else None
    all_employees = EmployeeProfile.objects.filter(employment_status="Active").order_by("full_name")
    all_teams = Team.objects.exclude(pk=pk).order_by("name") if pk else Team.objects.order_by("name")
    errors = {}
    if request.method == "POST":
        try:
            import re as _re
            if not obj:
                obj = Team()
            obj.name = request.POST.get("name", "").strip()
            if not obj.name:
                raise ValueError("Team name is required.")
            # Auto-generate code from name (keep existing code if editing)
            if not obj.code:
                base_code = _re.sub(r'[^A-Z0-9]', '', obj.name.upper())[:28] or "TEAM"
                candidate = base_code
                suffix = 1
                while Team.objects.filter(code=candidate).exclude(pk=obj.pk or 0).exists():
                    candidate = f"{base_code}{suffix}"
                    suffix += 1
                obj.code = candidate
            obj.department = request.POST.get("department", "").strip()
            obj.description = request.POST.get("description", "").strip()
            manager_pk = request.POST.get("manager")
            if not manager_pk:
                raise ValueError("Please select a team manager.")
            obj.manager = get_object_or_404(EmployeeProfile, pk=manager_pk)
            parent_pk = request.POST.get("parent_team")
            obj.parent_team_id = parent_pk if parent_pk else None
            obj.is_active = "is_active" in request.POST
            obj.created_by = request.user
            obj.save()
            messages.success(request, "Team saved.")
            return redirect("portal:hr_teams")
        except Exception as e:
            errors["general"] = str(e)
            if not pk:
                obj = None  # Reset so template doesn't try to render member section with pk=None
    team_members = obj.members.select_related("employee").order_by("employee__full_name") if obj else []
    role_choices = [("Member", "Member"), ("Lead", "Lead"), ("Coordinator", "Coordinator")]
    return render(request, "portal/hr/team_form.html", {
        "obj": obj, "all_employees": all_employees, "all_teams": all_teams, "errors": errors,
        "team_members": team_members, "role_choices": role_choices,
    })


@login_required
def hr_team_member_inline_add(request, team_pk):
    """AJAX: add a member to a team inline from the team edit page."""
    import json
    if not _hr_check(request):
        return JsonResponse({"error": "Forbidden"}, status=403)
    from teams.models import Team, TeamMember
    from accounts.models import EmployeeProfile
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)
    team = get_object_or_404(Team, pk=team_pk)
    emp_pk = request.POST.get("employee")
    role = request.POST.get("role_in_team", "Member")
    is_primary = request.POST.get("is_primary") == "true"
    if not emp_pk:
        return JsonResponse({"error": "Employee is required."}, status=400)
    emp = get_object_or_404(EmployeeProfile, pk=emp_pk)
    if TeamMember.objects.filter(team=team, employee=emp).exists():
        return JsonResponse({"error": f"{emp.full_name} is already a member of this team."}, status=400)
    try:
        tm = TeamMember.objects.create(team=team, employee=emp, role_in_team=role, is_primary=is_primary, joined_at=timezone.localdate())
        return JsonResponse({"id": tm.pk, "employee_id": emp.pk, "name": emp.full_name, "role": tm.role_in_team, "is_primary": tm.is_primary})
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=400)


@login_required
def hr_team_member_inline_update(request, pk):
    """AJAX: update a team member's role/primary flag inline."""
    if not _hr_check(request):
        return JsonResponse({"error": "Forbidden"}, status=403)
    from teams.models import TeamMember
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)
    tm = get_object_or_404(TeamMember, pk=pk)
    tm.role_in_team = request.POST.get("role_in_team", tm.role_in_team)
    tm.is_primary = request.POST.get("is_primary") == "true"
    try:
        tm.save()
        return JsonResponse({"id": tm.pk, "role": tm.role_in_team, "is_primary": tm.is_primary})
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=400)


@login_required
def hr_team_member_inline_remove(request, pk):
    """AJAX: remove a team member inline."""
    if not _hr_check(request):
        return JsonResponse({"error": "Forbidden"}, status=403)
    from teams.models import TeamMember
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)
    tm = get_object_or_404(TeamMember, pk=pk)
    try:
        tm.delete()
        return JsonResponse({"ok": True})
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=400)


@login_required
def hr_team_delete(request, pk):
    if not _hr_check(request):
        return redirect("portal:dashboard")
    from teams.models import Team
    obj = get_object_or_404(Team, pk=pk)
    if request.method == "POST":
        obj.delete()
        messages.success(request, "Team deleted.")
        return redirect("portal:hr_teams")
    return render(request, "portal/hr/confirm_delete.html", {
        "obj": obj, "back_url": "portal:hr_teams",
        "title": f"Delete Team â€” {obj.name}",
    })


# â”€â”€â”€ TEAM MEMBERS â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@login_required
def hr_team_members(request):
    if not _hr_check(request):
        return redirect("portal:dashboard")
    from teams.models import TeamMember, Team
    team_filter = request.GET.get("team", "")
    qs = TeamMember.objects.select_related("team", "employee").order_by("team__name", "employee__full_name")
    if team_filter:
        qs = qs.filter(team_id=team_filter)
    all_teams = Team.objects.order_by("name")
    return render(request, "portal/hr/team_members.html", {
        "items": qs, "all_teams": all_teams, "team_filter": team_filter,
    })


@login_required
def hr_team_member_edit(request, pk=None):
    if not _hr_check(request):
        return redirect("portal:dashboard")
    from teams.models import TeamMember, Team
    from accounts.models import EmployeeProfile
    obj = get_object_or_404(TeamMember, pk=pk) if pk else None
    all_employees = EmployeeProfile.objects.filter(employment_status="Active").order_by("full_name")
    all_teams = Team.objects.filter(is_active=True).order_by("name")
    errors = {}
    if request.method == "POST":
        try:
            emp_pk = request.POST.get("employee")
            team_pk = request.POST.get("team")
            emp = get_object_or_404(EmployeeProfile, pk=emp_pk)
            team = get_object_or_404(Team, pk=team_pk)
            if not obj:
                obj = TeamMember(employee=emp, team=team)
            obj.employee = emp
            obj.team = team
            obj.role_in_team = request.POST.get("role_in_team", "Member")
            obj.joined_at = request.POST.get("joined_at") or None
            obj.is_primary = "is_primary" in request.POST
            obj.save()
            messages.success(request, "Team member saved.")
            return redirect("portal:hr_team_members")
        except Exception as e:
            errors["general"] = str(e)
    import datetime
    return render(request, "portal/hr/team_member_form.html", {
        "obj": obj, "all_employees": all_employees, "all_teams": all_teams,
        "errors": errors, "today": datetime.date.today(),
        "role_choices": [("Member", "Member"), ("Lead", "Lead"), ("Coordinator", "Coordinator")],
    })


@login_required
def hr_team_member_delete(request, pk):
    if not _hr_check(request):
        return redirect("portal:dashboard")
    from teams.models import TeamMember
    obj = get_object_or_404(TeamMember, pk=pk)
    if request.method == "POST":
        obj.delete()
        messages.success(request, "Team member removed.")
        return redirect("portal:hr_team_members")
    return render(request, "portal/hr/confirm_delete.html", {
        "obj": obj, "back_url": "portal:hr_team_members",
        "title": f"Remove {obj.employee.full_name} from {obj.team.name}",
    })


# â”€â”€â”€ USERS â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@login_required
def hr_users(request):
    if not _hr_check(request):
        return redirect("portal:dashboard")
    from django.contrib.auth import get_user_model
    from accounts.models import EmployeeProfile
    User = get_user_model()
    q = request.GET.get("q", "").strip()
    qs = User.objects.select_related("employee_profile").order_by("username")
    if q:
        qs = qs.filter(username__icontains=q) | qs.filter(email__icontains=q)
    return render(request, "portal/hr/users.html", {"users": qs, "q": q})


@login_required
def hr_user_edit(request, pk=None):
    if not _hr_check(request):
        return redirect("portal:dashboard")
    from django.contrib.auth import get_user_model
    from accounts.models import EmployeeProfile
    User = get_user_model()
    user_obj = get_object_or_404(User, pk=pk) if pk else None
    errors = {}
    if request.method == "POST":
        try:
            if not user_obj:
                username = request.POST.get("username", "").strip()
                email = request.POST.get("email", "").strip()
                password = request.POST.get("password", "").strip()
                if not username or not password:
                    raise ValueError("Username and password are required.")
                user_obj = User.objects.create_user(username=username, email=email, password=password)
            else:
                user_obj.username = request.POST.get("username", user_obj.username).strip()
                user_obj.email = request.POST.get("email", user_obj.email).strip()
                new_pass = request.POST.get("password", "").strip()
                if new_pass:
                    user_obj.set_password(new_pass)
            user_obj.first_name = request.POST.get("first_name", "").strip()
            user_obj.last_name = request.POST.get("last_name", "").strip()
            user_obj.is_active = "is_active" in request.POST
            user_obj.is_staff = "is_staff" in request.POST
            user_obj.is_superuser = "is_superuser" in request.POST
            user_obj.save()
            # Update role on employee profile if exists
            try:
                profile = user_obj.employee_profile
                role = request.POST.get("role", "")
                if role:
                    profile.role = role
                    profile.save(update_fields=["role"])
            except EmployeeProfile.DoesNotExist:
                pass
            messages.success(request, f"User {user_obj.username} saved.")
            return redirect("portal:hr_users")
        except Exception as e:
            errors["general"] = str(e)
    role_choices = [("Employee", "Employee"), ("Manager", "Manager"), ("Approver", "Approver"), ("Super Admin", "Super Admin")]
    return render(request, "portal/hr/user_form.html", {
        "user_obj": user_obj, "errors": errors, "role_choices": role_choices,
    })


@login_required
def hr_user_delete(request, pk):
    if not _hr_check(request):
        return redirect("portal:dashboard")
    from django.contrib.auth import get_user_model
    User = get_user_model()
    user_obj = get_object_or_404(User, pk=pk)
    if user_obj == request.user:
        messages.error(request, "You cannot delete your own account.")
        return redirect("portal:hr_users")
    if request.method == "POST":
        user_obj.delete()
        messages.success(request, "User deleted.")
        return redirect("portal:hr_users")
    return render(request, "portal/hr/confirm_delete.html", {
        "obj": user_obj, "back_url": "portal:hr_users",
        "title": f"Delete User â€” {user_obj.username}",
    })
