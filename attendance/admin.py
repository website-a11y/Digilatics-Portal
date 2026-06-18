import calendar
import json
from datetime import date, timedelta

from django.contrib import admin, messages
from django.db.models import Count, Q
from django.shortcuts import render
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html

from accounts.models import EmployeeProfile
from .models import AttendancePolicy, AttendanceRecord, DeviceEmployee, PublicHoliday, Shift, SyncSchedule, SystemSetting
from .tz_utils import convert_time, get_display_tz_label


# ── helpers ──────────────────────────────────────────────────────────────────

def _is_manager(request):
    if request.user.is_superuser:
        return False
    profile = getattr(request.user, "employee_profile", None)
    return bool(profile and profile.role == EmployeeProfile.RoleChoices.MANAGER)


def _manager_team_qs(request):
    """Return EmployeeProfile queryset: the manager themselves + their direct reports + team members."""
    from django.db.models import Q
    profile = request.user.employee_profile
    return EmployeeProfile.objects.filter(
        Q(pk=profile.pk)
        | Q(reporting_manager=profile)
        | Q(team_memberships__team__manager=profile)
    ).distinct()


DAY_ABBR = ["M", "T", "W", "T", "F", "S", "S"]

STATUS_META = {
    "present":          {"label": "Present",           "bg": "#22c55e", "color": "#fff", "symbol": "✓"},
    "absent":           {"label": "Absent",            "bg": "#ef4444", "color": "#fff", "symbol": "✗"},
    "work_from_home":   {"label": "Work From Home",    "bg": "#3b82f6", "color": "#fff", "symbol": "⌂"},
    "on_leave_paid":    {"label": "On Leave (Paid)",   "bg": "#f97316", "color": "#fff", "symbol": "L"},
    "on_leave_unpaid":  {"label": "On Leave (Unpaid)", "bg": "#10b981", "color": "#fff", "symbol": "L"},
    "on_hourly_leave":  {"label": "On Hourly Leave",   "bg": "#1e293b", "color": "#fff", "symbol": "T"},
    "public_holiday":   {"label": "Public Holiday",    "bg": "#6366f1", "color": "#fff", "symbol": "H"},
    "half_day":         {"label": "Half Day",          "bg": "#eab308", "color": "#fff", "symbol": "½"},
    "weekend":          {"label": "Weekend",           "bg": None,      "color": "#94a3b8", "symbol": "W"},
    "future":           {"label": "—",                 "bg": None,      "color": "#cbd5e1", "symbol": "—"},
    "not_recorded":     {"label": "Not Recorded",      "bg": "#e2e8f0", "color": "#64748b", "symbol": "?"},
}

LEAVE_STATUSES = {"on_leave_paid", "on_leave_unpaid"}


def _month_bounds(year, month):
    _, last = calendar.monthrange(year, month)
    return date(year, month, 1), date(year, month, last)


def _prev_month(year, month):
    return (year - 1, 12) if month == 1 else (year, month - 1)


def _next_month(year, month):
    return (year + 1, 1) if month == 12 else (year, month + 1)


# ── Public Holiday admin ──────────────────────────────────────────────────────

@admin.register(PublicHoliday)
class PublicHolidayAdmin(admin.ModelAdmin):
    list_display = ("name", "start_date", "end_date", "description", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name",)
    ordering = ("-start_date",)
    list_editable = ("is_active",)

    def has_module_permission(self, request): return not _is_manager(request) and super().has_module_permission(request)
    def has_view_permission(self, request, obj=None): return not _is_manager(request) and super().has_view_permission(request, obj)
    def has_add_permission(self, request): return not _is_manager(request) and super().has_add_permission(request)
    def has_change_permission(self, request, obj=None): return not _is_manager(request) and super().has_change_permission(request, obj)
    def has_delete_permission(self, request, obj=None): return not _is_manager(request) and super().has_delete_permission(request, obj)


# ── Attendance Record admin ───────────────────────────────────────────────────

@admin.register(AttendanceRecord)
class AttendanceRecordAdmin(admin.ModelAdmin):
    change_list_template = "admin/attendance/attendancerecord/change_list.html"

    list_display = (
        "employee",
        "date",
        "status_badge",
        "leave_request_link",
        "check_in",
        "check_out",
        "late_badge",
        "early_checkout_badge",
        "notes",
    )
    list_filter = ("status", "date")
    search_fields = ("employee__full_name", "employee__employee_code")
    autocomplete_fields = ("employee",)
    ordering = ("-date",)
    actions = ["action_resync_from_leaves"]

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        if _is_manager(request):
            profile = request.user.employee_profile
            from accounts.models import EmployeeProfile as EP
            dept_qs = EP.objects.filter(department=profile.department).exclude(pk=profile.pk)
            return qs.filter(employee__in=dept_qs)
        return qs.none()

    def has_module_permission(self, request):
        if request.user.is_superuser:
            return True
        return _is_manager(request)

    def has_view_permission(self, request, obj=None):
        if request.user.is_superuser:
            return True
        if _is_manager(request):
            if obj is None:
                return True
            from accounts.models import EmployeeProfile as EP
            profile = request.user.employee_profile
            return EP.objects.filter(pk=obj.employee_id, department=profile.department).exists()
        return False

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    def get_readonly_fields(self, request, obj=None):
        # Once a record is linked to a leave request, lock status + dates.
        if obj and obj.leave_request_id:
            return ("leave_request_link", "created_at", "updated_at")
        return ("leave_request_link", "created_at", "updated_at")

    def get_fieldsets(self, request, obj=None):
        base = [
            (
                "Attendance",
                {
                    "fields": (
                        "employee",
                        "date",
                        "status",
                        ("check_in", "check_out"),
                        "notes",
                    )
                },
            ),
        ]
        # Show the leave-request panel only when editing an existing record.
        if obj:
            base.append(
                (
                    "Leave Integration",
                    {
                        "fields": ("leave_request_link",),
                        "description": (
                            "This record was auto-created from an approved leave request. "
                            "To change the status, update the leave request directly."
                            if obj.leave_request_id
                            else "No leave request linked to this attendance record."
                        ),
                    },
                )
            )
        base.append(
            ("Timestamps", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)})
        )
        return base

    # ── custom URLs ──────────────────────────────────────────────────────────

    def get_urls(self):
        urls = super().get_urls()
        return [
            path(
                "summary/",
                self.admin_site.admin_view(self.summary_view),
                name="attendance_summary",
            ),
            path(
                "employee/<int:employee_pk>/",
                self.admin_site.admin_view(self.employee_summary_view),
                name="attendance_employee_summary",
            ),
            path(
                "resync-leaves/",
                self.admin_site.admin_view(self.resync_leaves_view),
                name="attendance_resync_leaves",
            ),
            path(
                "device-status/",
                self.admin_site.admin_view(self.device_status_view),
                name="attendance_device_status",
            ),
            path(
                "manual-punch/",
                self.admin_site.admin_view(self.manual_punch_view),
                name="attendance_manual_punch",
            ),
            path(
                "force-refetch/",
                self.admin_site.admin_view(self.force_refetch_view),
                name="attendance_force_refetch",
            ),
        ] + urls

    # ── monthly grid view (replaces default changelist) ──────────────────────

    def changelist_view(self, request, extra_context=None):
        today = timezone.localdate()

        try:
            year = int(request.GET.get("year", today.year))
            month = int(request.GET.get("month", today.month))
            if not (1 <= month <= 12):
                raise ValueError
        except (ValueError, TypeError):
            year, month = today.year, today.month

        dept_filter = request.GET.get("dept", "")

        start, end = _month_bounds(year, month)
        days = [start + timedelta(days=i) for i in range((end - start).days + 1)]

        holidays = set(
            PublicHoliday.objects.filter(
                date__range=(start, end), is_active=True
            ).values_list("date", flat=True)
        )

        # All active employees (scoped to manager's team when applicable)
        _emp_base = EmployeeProfile.objects.filter(
            employment_status=EmployeeProfile.EmploymentStatusChoices.ACTIVE
        ).select_related("user", "reporting_manager").order_by("department", "full_name")
        if _is_manager(request):
            _emp_base = _emp_base.filter(pk__in=_manager_team_qs(request))
        all_employees = list(_emp_base)

        # Distinct sorted departments
        departments = sorted(set(e.department for e in all_employees if e.department))

        # Employees shown in grid (filtered by dept if selected)
        grid_employees = (
            [e for e in all_employees if e.department == dept_filter]
            if dept_filter else all_employees
        )

        # Fetch all records once
        records = AttendanceRecord.objects.filter(
            date__range=(start, end)
        ).select_related("employee", "leave_request__leave_type")

        record_map: dict[int, dict[date, AttendanceRecord]] = {}
        for rec in records:
            record_map.setdefault(rec.employee_id, {})[rec.date] = rec

        # ── Build display grid (filtered employees) ───────────────────────────
        def _build_cells(emp):
            emp_records = record_map.get(emp.pk, {})
            cells = []
            for day in days:
                is_weekend = day.weekday() >= 5
                is_holiday = day in holidays
                is_future = day > today
                rec = emp_records.get(day)

                if rec:
                    status_key = rec.status
                elif is_holiday:
                    status_key = "public_holiday"
                elif is_weekend:
                    status_key = "weekend"
                elif is_future:
                    status_key = "future"
                else:
                    status_key = "not_recorded"

                tz_lbl = get_display_tz_label()
                tooltip_parts = [STATUS_META[status_key]["label"]]
                if rec:
                    if rec.check_in:
                        in_label = convert_time(rec.check_in, day)
                        if rec.is_late:
                            in_label += " ⚠ Late"
                        tooltip_parts.append(f"In: {in_label} {tz_lbl}")
                    if rec.check_out:
                        out_label = convert_time(rec.check_out, day)
                        if rec.is_early_checkout:
                            out_label += " ⚠ Early Out"
                        tooltip_parts.append(f"Out: {out_label} {tz_lbl}")
                    if rec.leave_request_id:
                        lr = rec.leave_request
                        tooltip_parts.append(
                            f"Leave: {lr.leave_type.name} ({lr.from_date} → {lr.to_date})"
                        )
                    if rec.notes:
                        tooltip_parts.append(rec.notes)

                cells.append({
                    "day": day,
                    "record": rec,
                    "status_key": status_key,
                    "meta": STATUS_META[status_key],
                    "is_weekend": is_weekend,
                    "is_holiday": is_holiday,
                    "is_future": is_future,
                    "is_today": day == today,
                    "is_leave_synced": bool(rec and rec.leave_request_id),
                    "tooltip": " · ".join(tooltip_parts),
                })
            return cells

        grid = [{"employee": emp, "cells": _build_cells(emp)} for emp in grid_employees]

        # ── Overall summary counts (from filtered grid) ───────────────────────
        all_cells_flat = [
            c for row in grid
            for c in row["cells"]
            if not c["is_weekend"] and not c["is_future"]
        ]
        summary_counts: dict[str, int] = {}
        for c in all_cells_flat:
            summary_counts[c["status_key"]] = summary_counts.get(c["status_key"], 0) + 1

        # ── Department breakdown (always all employees) ───────────────────────
        LEAVE_KEYS = {"on_leave_paid", "on_leave_unpaid", "on_hourly_leave", "half_day"}

        dept_map: dict[str, dict] = {}
        for emp in all_employees:
            dept = emp.department or "—"
            if dept not in dept_map:
                dept_map[dept] = {
                    "name": dept,
                    "total_emp": 0,
                    "present": 0,
                    "absent": 0,
                    "leave": 0,
                    "holiday": 0,
                    "not_recorded": 0,
                    "pct": 0,
                }
            dept_map[dept]["total_emp"] += 1
            emp_recs = record_map.get(emp.pk, {})

            for day in days:
                if day.weekday() >= 5 or day > today:
                    continue
                if day in holidays:
                    dept_map[dept]["holiday"] += 1
                    continue
                rec = emp_recs.get(day)
                if rec:
                    sk = rec.status
                    if sk == "present":
                        dept_map[dept]["present"] += 1
                    elif sk == "absent":
                        dept_map[dept]["absent"] += 1
                    elif sk in LEAVE_KEYS:
                        dept_map[dept]["leave"] += 1
                    else:
                        dept_map[dept]["not_recorded"] += 1
                else:
                    dept_map[dept]["not_recorded"] += 1

        for ds in dept_map.values():
            effective = ds["present"] + ds["absent"] + ds["leave"]
            ds["pct"] = round(ds["present"] / effective * 100) if effective else 0

        dept_rows = sorted(dept_map.values(), key=lambda x: x["name"])

        # ── Build context ─────────────────────────────────────────────────────
        prev_year, prev_month = _prev_month(year, month)
        next_year, next_month = _next_month(year, month)

        # ── 12-month chart data ───────────────────────────────────────────────
        chart_months = []
        yr_c, mo_c = today.year, today.month
        for i in range(11, -1, -1):
            mo_i = mo_c - i
            yr_i = yr_c
            while mo_i <= 0:
                mo_i += 12
                yr_i -= 1
            chart_months.append((yr_i, mo_i, date(yr_i, mo_i, 1).strftime("%b")))

        start_12 = date(chart_months[0][0], chart_months[0][1], 1)
        chart_records = (
            AttendanceRecord.objects
            .filter(date__gte=start_12, status__in=["present", "absent"])
            .values("date__year", "date__month", "status", "is_late")
            .annotate(cnt=Count("id"))
        )
        chart_lookup: dict[tuple, dict] = {}
        for r in chart_records:
            key = (r["date__year"], r["date__month"])
            if key not in chart_lookup:
                chart_lookup[key] = {"present": 0, "late": 0, "absent": 0}
            if r["status"] == "absent":
                chart_lookup[key]["absent"] += r["cnt"]
            elif r["is_late"]:
                chart_lookup[key]["late"] += r["cnt"]
            else:
                chart_lookup[key]["present"] += r["cnt"]

        annual_chart = json.dumps({
            "labels": [m[2] for m in chart_months],
            "present": [chart_lookup.get((m[0], m[1]), {}).get("present", 0) for m in chart_months],
            "late":    [chart_lookup.get((m[0], m[1]), {}).get("late",    0) for m in chart_months],
            "absent":  [chart_lookup.get((m[0], m[1]), {}).get("absent",  0) for m in chart_months],
        })

        # ── Employee type breakdown ───────────────────────────────────────────
        emp_type_qs = (
            EmployeeProfile.objects
            .filter(employment_status=EmployeeProfile.EmploymentStatusChoices.ACTIVE)
            .values("employment_type")
            .annotate(cnt=Count("id"))
            .order_by("employment_type")
        )
        emp_type_chart = json.dumps({
            "labels": [r["employment_type"] for r in emp_type_qs],
            "data":   [r["cnt"] for r in emp_type_qs],
        })

        context = {
            **self.admin_site.each_context(request),
            "title": "Attendance — Monthly View",
            "opts": self.model._meta,
            "app_label": self.model._meta.app_label,
            "has_add_permission": self.has_add_permission(request),
            "grid": grid,
            "days": days,
            "day_abbr": DAY_ABBR,
            "month_label": start.strftime("%b %Y"),
            "year": year,
            "month": month,
            "prev_year": prev_year,
            "prev_month": prev_month,
            "next_year": next_year,
            "next_month": next_month,
            "today": today,
            "status_meta": STATUS_META,
            "summary_counts": summary_counts,
            # department stuff
            "departments": departments,
            "dept_filter": dept_filter,
            "dept_rows": dept_rows,
            # charts
            "annual_chart_json": annual_chart,
            "emp_type_chart_json": emp_type_chart,
        }
        return render(request, self.change_list_template, context)

    # ── summary view ─────────────────────────────────────────────────────────

    def summary_view(self, request):
        today = timezone.localdate()
        period = request.GET.get("period", "daily")

        if period == "weekly":
            start = today - timedelta(days=today.weekday())
            end = start + timedelta(days=6)
            title = f"Weekly Summary — {start.strftime('%d %b')} to {end.strftime('%d %b %Y')}"
        elif period == "monthly":
            start, end = _month_bounds(today.year, today.month)
            title = f"Monthly Summary — {today.strftime('%B %Y')}"
        else:
            period = "daily"
            start = end = today
            title = f"Daily Summary — {today.strftime('%A, %d %b %Y')}"

        records = AttendanceRecord.objects.filter(
            date__range=(start, end)
        ).select_related("employee")

        total_employees = EmployeeProfile.objects.filter(
            employment_status=EmployeeProfile.EmploymentStatusChoices.ACTIVE
        ).count()

        status_counts = {
            item["status"]: item["cnt"]
            for item in records.values("status").annotate(cnt=Count("id"))
        }

        holidays = set(
            PublicHoliday.objects.filter(
                date__range=(start, end), is_active=True
            ).values_list("date", flat=True)
        )
        range_days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
        working_days = [d for d in range_days if d.weekday() < 5 and d not in holidays]

        emp_stats: dict[int, dict[str, int]] = {}
        for rec in records:
            emp_stats.setdefault(rec.employee_id, {})
            emp_stats[rec.employee_id][rec.status] = (
                emp_stats[rec.employee_id].get(rec.status, 0) + 1
            )

        employees = EmployeeProfile.objects.filter(
            employment_status=EmployeeProfile.EmploymentStatusChoices.ACTIVE
        ).order_by("full_name")
        if _is_manager(request):
            employees = employees.filter(pk__in=_manager_team_qs(request))

        employee_rows = []
        for emp in employees:
            stats = emp_stats.get(emp.pk, {})
            present = stats.get("present", 0)
            absent = stats.get("absent", 0)
            lp = stats.get("on_leave_paid", 0)
            lu = stats.get("on_leave_unpaid", 0)
            hl = stats.get("on_hourly_leave", 0)
            hd = stats.get("half_day", 0)
            ph = stats.get("public_holiday", 0)
            total_recorded = present + absent + lp + lu + hl + hd + ph
            pct = round(present / total_recorded * 100) if total_recorded else 0
            employee_rows.append(
                {
                    "employee": emp,
                    "present": present,
                    "absent": absent,
                    "leave_paid": lp,
                    "leave_unpaid": lu,
                    "hourly_leave": hl,
                    "half_day": hd,
                    "public_holiday": ph,
                    "total": total_recorded,
                    "attendance_pct": pct,
                }
            )

        # ── Department breakdown ──────────────────────────────────────────────
        dept_map: dict[str, dict] = {}
        for row in employee_rows:
            dept = row["employee"].department or "—"
            if dept not in dept_map:
                dept_map[dept] = {
                    "name": dept,
                    "total_emp": 0,
                    "present": 0,
                    "absent": 0,
                    "leave_paid": 0,
                    "leave_unpaid": 0,
                    "hourly_leave": 0,
                    "half_day": 0,
                    "public_holiday": 0,
                    "total": 0,
                    "pct": 0,
                }
            d = dept_map[dept]
            d["total_emp"] += 1
            d["present"] += row["present"]
            d["absent"] += row["absent"]
            d["leave_paid"] += row["leave_paid"]
            d["leave_unpaid"] += row["leave_unpaid"]
            d["hourly_leave"] += row["hourly_leave"]
            d["half_day"] += row["half_day"]
            d["public_holiday"] += row["public_holiday"]
            d["total"] += row["total"]

        for ds in dept_map.values():
            ds["leave"] = ds["leave_paid"] + ds["leave_unpaid"] + ds["hourly_leave"] + ds["half_day"]
            ds["pct"] = round(ds["present"] / ds["total"] * 100) if ds["total"] else 0

        dept_summary_rows = sorted(dept_map.values(), key=lambda x: x["name"])

        context = {
            **self.admin_site.each_context(request),
            "title": title,
            "opts": self.model._meta,
            "app_label": self.model._meta.app_label,
            "period": period,
            "start": start,
            "end": end,
            "today": today,
            "total_employees": total_employees,
            "working_days": len(working_days),
            "status_counts": status_counts,
            "present_count": status_counts.get("present", 0),
            "absent_count": status_counts.get("absent", 0),
            "leave_paid_count": status_counts.get("on_leave_paid", 0),
            "leave_unpaid_count": status_counts.get("on_leave_unpaid", 0),
            "hourly_leave_count": status_counts.get("on_hourly_leave", 0),
            "half_day_count": status_counts.get("half_day", 0),
            "public_holiday_count": status_counts.get("public_holiday", 0),
            "employee_rows": employee_rows,
            "dept_summary_rows": dept_summary_rows,
            "status_meta": STATUS_META,
        }
        return render(request, "admin/attendance/summary.html", context)

    # ── per-employee summary view ─────────────────────────────────────────────

    def employee_summary_view(self, request, employee_pk):
        from django.shortcuts import get_object_or_404
        from django.http import HttpResponseForbidden

        employee = get_object_or_404(EmployeeProfile, pk=employee_pk)

        if _is_manager(request):
            if not _manager_team_qs(request).filter(pk=employee.pk).exists():
                return HttpResponseForbidden("You do not have access to this employee's attendance.")

        today = timezone.localdate()

        try:
            year = int(request.GET.get("year", today.year))
            month = int(request.GET.get("month", today.month))
            if not (1 <= month <= 12):
                raise ValueError
        except (ValueError, TypeError):
            year, month = today.year, today.month

        start, end = _month_bounds(year, month)
        days = [start + timedelta(days=i) for i in range((end - start).days + 1)]

        holidays = set(
            PublicHoliday.objects.filter(
                date__range=(start, end), is_active=True
            ).values_list("date", flat=True)
        )

        records_qs = AttendanceRecord.objects.filter(
            employee=employee,
            date__range=(start, end),
        ).select_related("leave_request__leave_type").order_by("date")

        record_map = {rec.date: rec for rec in records_qs}

        # ── Counts ────────────────────────────────────────────────────────────
        present = absent = late = early_checkout = 0
        leave_paid = leave_unpaid = hourly_leave = half_day = holiday = not_recorded = 0
        working_days = 0

        day_rows = []
        for day in days:
            is_weekend = day.weekday() >= 5
            is_future = day > today
            is_holiday = day in holidays
            rec = record_map.get(day)

            if is_weekend:
                status_key = "weekend"
            elif is_future:
                status_key = "future"
            elif is_holiday and not rec:
                status_key = "public_holiday"
                holiday += 1
                working_days += 1
            elif rec:
                status_key = rec.status
                working_days += 1
                if rec.status == AttendanceRecord.StatusChoices.PRESENT:
                    present += 1
                    if rec.is_late:
                        late += 1
                    if rec.is_early_checkout:
                        early_checkout += 1
                elif rec.status == AttendanceRecord.StatusChoices.ABSENT:
                    absent += 1
                elif rec.status == AttendanceRecord.StatusChoices.ON_LEAVE_PAID:
                    leave_paid += 1
                elif rec.status == AttendanceRecord.StatusChoices.ON_LEAVE_UNPAID:
                    leave_unpaid += 1
                elif rec.status == AttendanceRecord.StatusChoices.ON_HOURLY_LEAVE:
                    hourly_leave += 1
                    if rec.is_late:
                        late += 1
                    if rec.is_early_checkout:
                        early_checkout += 1
                elif rec.status == AttendanceRecord.StatusChoices.HALF_DAY:
                    half_day += 1
                elif rec.status == AttendanceRecord.StatusChoices.PUBLIC_HOLIDAY:
                    holiday += 1
            else:
                status_key = "not_recorded"
                not_recorded += 1
                working_days += 1

            if not is_weekend and not is_future:
                day_rows.append({
                    "day": day,
                    "record": rec,
                    "status_key": status_key,
                    "meta": STATUS_META.get(status_key, STATUS_META["not_recorded"]),
                    "is_holiday": is_holiday,
                    "is_today": day == today,
                })

        attendance_pct = round(present / working_days * 100) if working_days else 0

        prev_year, prev_month = _prev_month(year, month)
        next_year, next_month = _next_month(year, month)

        context = {
            **self.admin_site.each_context(request),
            "title": f"{employee.full_name} — Attendance",
            "opts": self.model._meta,
            "app_label": self.model._meta.app_label,
            "employee": employee,
            "month_label": start.strftime("%B %Y"),
            "year": year,
            "month": month,
            "prev_year": prev_year,
            "prev_month": prev_month,
            "next_year": next_year,
            "next_month": next_month,
            "today": today,
            "day_rows": day_rows,
            "status_meta": STATUS_META,
            # counts
            "present": present,
            "absent": absent,
            "late": late,
            "early_checkout": early_checkout,
            "leave_paid": leave_paid,
            "leave_unpaid": leave_unpaid,
            "hourly_leave": hourly_leave,
            "half_day": half_day,
            "holiday": holiday,
            "not_recorded": not_recorded,
            "working_days": working_days,
            "attendance_pct": attendance_pct,
        }
        return render(request, "admin/attendance/employee_summary.html", context)

    # ── re-sync all approved leaves view ─────────────────────────────────────

    def resync_leaves_view(self, request):
        if request.method == "POST":
            from attendance.services import resync_all_approved_leaves
            count = resync_all_approved_leaves()
            self.message_user(
                request,
                f"Re-sync complete — {count} approved leave request(s) processed.",
                level=messages.SUCCESS,
            )
        from django.http import HttpResponseRedirect
        return HttpResponseRedirect(
            reverse("admin:attendance_attendancerecord_changelist")
        )

    # ── force device re-fetch view ────────────────────────────────────────────

    def force_refetch_view(self, request):
        """
        Drop a flag file so the next ADMS getrequest poll (within 1 minute)
        responds with a DATA QUERY covering the last 7 days, forcing the device
        to re-upload all recent punches.
        """
        if request.method == "POST":
            from attendance.views import force_adms_data_query
            from attendance.models import DeviceSyncFlag
            from datetime import date, timedelta
            force_adms_data_query()
            DeviceSyncFlag.request(date.today() - timedelta(days=7))
            self.message_user(
                request,
                "Re-fetch requested — the device will re-upload the last 7 days of "
                "punches on its next poll (within 1 minute).",
                level=messages.SUCCESS,
            )
        from django.http import HttpResponseRedirect
        return HttpResponseRedirect(
            reverse("admin:attendance_attendancerecord_changelist")
        )

    # ── admin action ─────────────────────────────────────────────────────────

    @admin.action(description="Re-sync selected records from their leave requests")
    def action_resync_from_leaves(self, request, queryset):
        from attendance.services import sync_leave_request_to_attendance

        leave_request_ids = set(
            queryset.filter(
                leave_request__isnull=False
            ).values_list("leave_request_id", flat=True)
        )
        if not leave_request_ids:
            self.message_user(
                request,
                "No selected records are linked to a leave request.",
                level=messages.WARNING,
            )
            return

        from leaves.models import LeaveRequest
        synced = 0
        for lr in LeaveRequest.objects.filter(
            pk__in=leave_request_ids
        ).select_related("employee", "leave_type"):
            sync_leave_request_to_attendance(lr)
            synced += 1

        self.message_user(
            request,
            f"Re-synced attendance from {synced} leave request(s).",
            level=messages.SUCCESS,
        )

    # ── display helpers ───────────────────────────────────────────────────────

    @admin.display(description="Status")
    def status_badge(self, obj: AttendanceRecord):
        meta = STATUS_META.get(obj.status, {})
        bg = meta.get("bg", "#e2e8f0")
        color = meta.get("color", "#333")
        label = obj.get_status_display()
        return format_html(
            '<span style="background:{};color:{};padding:3px 10px;'
            'border-radius:999px;font-size:11px;font-weight:700;">{}</span>',
            bg,
            color,
            label,
        )

    @admin.display(description="Late", boolean=False)
    def late_badge(self, obj: AttendanceRecord):
        if obj.is_late:
            return format_html(
                '<span style="background:#ef4444;color:#fff;padding:2px 8px;'
                'border-radius:999px;font-size:11px;font-weight:700;">Late</span>'
            )
        return "—"

    @admin.display(description="Early Out", boolean=False)
    def early_checkout_badge(self, obj: AttendanceRecord):
        if obj.is_early_checkout:
            return format_html(
                '<span style="background:#f97316;color:#fff;padding:2px 8px;'
                'border-radius:999px;font-size:11px;font-weight:700;">Early</span>'
            )
        return "—"

    @admin.display(description="Leave Request")
    def leave_request_link(self, obj: AttendanceRecord):
        if not obj.leave_request_id:
            return "—"
        lr = obj.leave_request
        url = reverse("admin:leaves_leaverequest_change", args=[lr.pk])
        return format_html(
            '<a href="{}" style="font-size:12px;font-weight:600;">'
            "{} · {} → {} · {}"
            "</a>",
            url,
            lr.leave_type.name,
            lr.from_date,
            lr.to_date,
            lr.status,
        )

    # ── manual punch view ────────────────────────────────────────────────────

    def manual_punch_view(self, request):
        import datetime
        from attendance.services import compute_attendance_flags

        today = timezone.localdate()
        success_msg = error_msg = None

        manager_profile = None
        if _is_manager(request):
            manager_profile = getattr(request.user, "employee_profile", None)

        can_punch = request.user.is_superuser or (_is_manager(request) and manager_profile is not None)

        if request.method == "POST":
            if not can_punch:
                from django.http import HttpResponseForbidden
                return HttpResponseForbidden("You do not have permission to punch.")

            action = request.POST.get("action", "single")

            # ── Bulk check-in ──────────────────────────────────────────────────
            if action == "bulk_checkin" and request.user.is_superuser:
                time_str = request.POST.get("bulk_time", "").strip()
                try:
                    bulk_time = datetime.datetime.strptime(time_str, "%H:%M").time() if time_str else timezone.localtime().time().replace(second=0, microsecond=0)
                except ValueError:
                    bulk_time = timezone.localtime().time().replace(second=0, microsecond=0)

                pks = request.POST.getlist("selected_employees")
                if not pks:
                    error_msg = "No employees selected."
                else:
                    marked = 0
                    for pk in pks:
                        try:
                            emp = EmployeeProfile.objects.get(pk=pk)
                            record, _ = AttendanceRecord.objects.get_or_create(
                                employee=emp,
                                date=today,
                                defaults={
                                    "status": AttendanceRecord.StatusChoices.PRESENT,
                                    "notes": "Bulk check-in from dashboard",
                                },
                            )
                            record.check_in = bulk_time
                            record.status = AttendanceRecord.StatusChoices.PRESENT
                            flags = compute_attendance_flags(emp, bulk_time, None)
                            record.is_late = flags["is_late"]
                            record.notes = "Bulk check-in from dashboard"
                            record.save()
                            marked += 1
                        except Exception:
                            pass
                    success_msg = f"Checked in {marked} employee(s) at {bulk_time.strftime('%H:%M')}."

            # ── Single punch ───────────────────────────────────────────────────
            else:
                employee_pk = request.POST.get("employee_pk")
                punch_type = request.POST.get("punch_type")
                time_str = request.POST.get("punch_time", "").strip()

                try:
                    employee = EmployeeProfile.objects.get(pk=employee_pk)

                    if _is_manager(request) and (manager_profile is None or str(employee.pk) != str(manager_profile.pk)):
                        raise Exception("You can only punch your own attendance from here.")

                    punch_time = (
                        datetime.datetime.strptime(time_str, "%H:%M").time()
                        if time_str
                        else timezone.localtime().time().replace(second=0, microsecond=0)
                    )

                    record, created = AttendanceRecord.objects.get_or_create(
                        employee=employee,
                        date=today,
                        defaults={
                            "status": AttendanceRecord.StatusChoices.PRESENT,
                            "notes": "Manual punch from dashboard",
                        },
                    )

                    if punch_type == "in":
                        record.check_in = punch_time
                        if record.status not in (
                            AttendanceRecord.StatusChoices.PRESENT,
                            AttendanceRecord.StatusChoices.HALF_DAY,
                        ):
                            record.status = AttendanceRecord.StatusChoices.PRESENT
                    else:
                        record.check_out = punch_time

                    if not created and not record.notes:
                        record.notes = "Manual punch from dashboard"

                    flags = compute_attendance_flags(employee, record.check_in, record.check_out)
                    record.is_late = flags["is_late"]
                    record.is_early_checkout = flags["is_early_checkout"]
                    record.save()

                    label = "Check-in" if punch_type == "in" else "Check-out"
                    success_msg = (
                        f"{label} recorded for {employee.full_name} at {punch_time.strftime('%H:%M')}"
                        + (" (Late)" if punch_type == "in" and flags["is_late"] else "")
                        + (" (Early checkout)" if punch_type == "out" and flags["is_early_checkout"] else "")
                    )
                except EmployeeProfile.DoesNotExist:
                    error_msg = "Employee not found."
                except Exception as exc:
                    error_msg = str(exc)

        # ── Build employee rows ────────────────────────────────────────────────
        employees_qs = (
            EmployeeProfile.objects
            .filter(employment_status=EmployeeProfile.EmploymentStatusChoices.ACTIVE)
            .order_by("department", "full_name")
        )
        if _is_manager(request):
            employees_qs = employees_qs.filter(pk__in=_manager_team_qs(request))

        today_records = {
            r.employee_id: r
            for r in AttendanceRecord.objects.filter(date=today).select_related("employee")
        }

        rows = []
        checked_in = not_checked_in = 0
        for emp in employees_qs:
            rec = today_records.get(emp.pk)
            if rec and rec.check_in:
                checked_in += 1
            else:
                not_checked_in += 1
            rows.append({
                "employee": emp,
                "record": rec,
                "check_in": rec.check_in if rec else None,
                "check_out": rec.check_out if rec else None,
                "status": rec.status if rec else None,
                "is_late": rec.is_late if rec else False,
                "is_early_checkout": rec.is_early_checkout if rec else False,
            })

        context = {
            **self.admin_site.each_context(request),
            "title": "Manual Punch",
            "opts": self.model._meta,
            "app_label": self.model._meta.app_label,
            "today": today,
            "today_str": today.strftime("%A, %d %b %Y"),
            "rows": rows,
            "checked_in": checked_in,
            "not_checked_in": not_checked_in,
            "total_employees": len(rows),
            "can_punch": can_punch,
            "manager_self_pk": manager_profile.pk if manager_profile else None,
            "success_msg": success_msg,
            "error_msg": error_msg,
            "status_meta": STATUS_META,
        }
        return render(request, "admin/attendance/manual_punch.html", context)

    # ── ADMS device status view ───────────────────────────────────────────────

    def device_status_view(self, request):
        from django.conf import settings
        import socket

        cfg = getattr(settings, "ZK_DEVICE", {})
        host = cfg.get("host", "—")
        port = cfg.get("port", 4370)

        # Check if device is reachable on TCP (pull mode test — informational only)
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(3)
        try:
            s.connect((host, port))
            s.close()
            tcp_reachable = True
        except Exception:
            tcp_reachable = False

        today = timezone.localdate()
        # Recent ADMS-pushed records (last 20 from today)
        recent_records = (
            AttendanceRecord.objects
            .filter(notes__icontains="ZKTeco ADMS")
            .select_related("employee")
            .order_by("-updated_at")[:20]
        )

        # Count today's ADMS synced records
        today_adms_count = AttendanceRecord.objects.filter(
            date=today, notes__icontains="ZKTeco ADMS"
        ).count()

        # Last received punch time
        last_push = (
            AttendanceRecord.objects
            .filter(notes__icontains="ZKTeco ADMS")
            .order_by("-updated_at")
            .first()
        )

        # Detect server's own LAN IP to show in device config guide
        import socket as _sock
        try:
            server_ip = _sock.gethostbyname(_sock.gethostname())
        except Exception:
            server_ip = "your-server-ip"

        # Determine port server is running on (best-guess from request)
        server_port = request.META.get("SERVER_PORT", "8000")

        context = {
            **self.admin_site.each_context(request),
            "title": "Device Status — ADMS Push Mode",
            "opts": self.model._meta,
            "app_label": self.model._meta.app_label,
            "host": host,
            "port": port,
            "tcp_reachable": tcp_reachable,
            "server_ip": server_ip,
            "server_port": server_port,
            "today": today,
            "today_adms_count": today_adms_count,
            "last_push": last_push,
            "recent_records": recent_records,
            "device_mapping_count": DeviceEmployee.objects.count(),
        }
        return render(request, "admin/attendance/device_status.html", context)


# ── Device Employee Mapping admin ─────────────────────────────────────────────

@admin.register(DeviceEmployee)
class DeviceEmployeeAdmin(admin.ModelAdmin):
    change_list_template = "admin/attendance/deviceemployee/change_list.html"
    list_display = ("device_user_id", "employee_name", "employee_code", "department")
    search_fields = (
        "employee__full_name",
        "employee__employee_code",
        "device_user_id",
    )
    autocomplete_fields = ("employee",)
    ordering = ("device_user_id",)

    def get_urls(self):
        from django.urls import path
        urls = super().get_urls()
        return [
            path(
                "auto-map/",
                self.admin_site.admin_view(self.auto_map_view),
                name="attendance_deviceemployee_automap",
            ),
        ] + urls

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context["auto_map_url"] = "auto-map/"
        return super().changelist_view(request, extra_context=extra_context)

    def auto_map_view(self, request):
        from django.http import HttpResponseRedirect
        from django.urls import reverse
        if not request.user.is_superuser:
            messages.error(request, "Only superusers can run the auto-map.")
            return HttpResponseRedirect("../")
        try:
            from io import StringIO
            from django.core.management import call_command
            buf = StringIO()
            call_command("auto_map_from_employee_code", stdout=buf)
            output = buf.getvalue()
            created = updated = skipped = 0
            for line in output.splitlines():
                if line.strip().startswith("Created"):
                    try: created = int(line.split(":")[1].strip())
                    except Exception: pass
                elif line.strip().startswith("Updated"):
                    try: updated = int(line.split(":")[1].strip())
                    except Exception: pass
                elif line.strip().startswith("Skipped"):
                    try: skipped = int(line.split(":")[1].strip())
                    except Exception: pass
            messages.success(
                request,
                f"Auto-map complete — {created} created, {updated} updated, {skipped} skipped (non-numeric codes).",
            )
        except Exception as exc:
            messages.error(request, f"Auto-map failed: {exc}")
        return HttpResponseRedirect(
            reverse("admin:attendance_deviceemployee_changelist")
        )

    def has_module_permission(self, request): return not _is_manager(request) and super().has_module_permission(request)
    def has_view_permission(self, request, obj=None): return not _is_manager(request) and super().has_view_permission(request, obj)
    def has_add_permission(self, request): return not _is_manager(request) and super().has_add_permission(request)
    def has_change_permission(self, request, obj=None): return not _is_manager(request) and super().has_change_permission(request, obj)
    def has_delete_permission(self, request, obj=None): return not _is_manager(request) and super().has_delete_permission(request, obj)

    @admin.display(description="Employee", ordering="employee__full_name")
    def employee_name(self, obj):
        return obj.employee.full_name

    @admin.display(description="Code", ordering="employee__employee_code")
    def employee_code(self, obj):
        return obj.employee.employee_code

    @admin.display(description="Department", ordering="employee__department")
    def department(self, obj):
        return obj.employee.department


# ── Sync Schedule admin ───────────────────────────────────────────────────────

@admin.register(SyncSchedule)
class SyncScheduleAdmin(admin.ModelAdmin):
    change_list_template = "admin/attendance/syncschedule/change_list.html"
    change_form_template = "admin/attendance/syncschedule/change_form.html"
    list_display = ("sync_times", "is_active", "updated_at")
    list_editable = ("is_active",)

    def has_module_permission(self, request): return not _is_manager(request) and super().has_module_permission(request)
    def has_view_permission(self, request, obj=None): return not _is_manager(request) and super().has_view_permission(request, obj)

    def has_add_permission(self, request):
        if _is_manager(request):
            return False
        return not SyncSchedule.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description="Sync Times")
    def sync_times(self, obj):
        return f"{obj.sync_time_1.strftime('%H:%M')} & {obj.sync_time_2.strftime('%H:%M')}"


# ── Attendance Policy admin ───────────────────────────────────────────────────

@admin.register(AttendancePolicy)
class AttendancePolicyAdmin(admin.ModelAdmin):
    change_list_template = "admin/attendance/attendancepolicy/change_list.html"
    list_display = ("policy_summary", "checkin_buffer_minutes", "checkout_buffer_minutes", "updated_at")

    fieldsets = (
        (
            "Buffer Settings",
            {
                "fields": ("checkin_buffer_minutes", "checkout_buffer_minutes"),
                "description": (
                    "These buffers apply globally to all employees. "
                    "Set each employee's scheduled check-in / check-out times on their profile."
                ),
            },
        ),
    )

    def has_module_permission(self, request): return not _is_manager(request) and super().has_module_permission(request)
    def has_view_permission(self, request, obj=None): return not _is_manager(request) and super().has_view_permission(request, obj)

    def has_add_permission(self, request):
        if _is_manager(request):
            return False
        return not AttendancePolicy.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        try:
            policy = AttendancePolicy.objects.first()
        except AttendancePolicy.DoesNotExist:
            policy = None
        extra_context["policy"] = policy
        return super().changelist_view(request, extra_context=extra_context)

    @admin.display(description="Policy")
    def policy_summary(self, obj):
        return (
            f"Check-in: ±{obj.checkin_buffer_minutes} min  |  "
            f"Check-out: ±{obj.checkout_buffer_minutes} min"
        )


# ══════════════════════════════════════════════════════════════════════════════
# SHIFT MASTER
# ══════════════════════════════════════════════════════════════════════════════

@admin.register(Shift)
class ShiftAdmin(admin.ModelAdmin):
    change_list_template = "admin/attendance/shift/change_list.html"
    list_display = (
        "name", "start_time_display", "end_time_display",
        "working_hours_display", "employee_count_display", "is_active",
    )
    list_filter = ("is_active",)
    search_fields = ("name",)
    fieldsets = (
        (
            "Shift Details",
            {
                "fields": (
                    "name",
                    ("start_time", "end_time"),
                    "is_active",
                    "notes",
                ),
                "description": (
                    "Define a shift template. Employees assigned to this shift "
                    "will have their scheduled check-in and check-out times set automatically."
                ),
            },
        ),
    )

    @admin.display(description="Start Time")
    def start_time_display(self, obj):
        return format_html(
            '<span style="font-weight:600;color:#16a34a;">{}</span>',
            obj.start_time.strftime("%I:%M %p"),
        )

    @admin.display(description="End Time")
    def end_time_display(self, obj):
        return format_html(
            '<span style="font-weight:600;color:#dc2626;">{}</span>',
            obj.end_time.strftime("%I:%M %p"),
        )

    @admin.display(description="Working Hours")
    def working_hours_display(self, obj):
        return format_html(
            '<span style="font-weight:700;">{} hrs</span>',
            obj.working_hours,
        )

    @admin.display(description="Employees")
    def employee_count_display(self, obj):
        count = obj.employees.filter(employment_status="Active").count()
        return format_html('<strong>{}</strong>', count) if count else "0"

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context["all_shifts"] = list(
            Shift.objects.all().order_by("start_time", "name")
        )
        return super().changelist_view(request, extra_context=extra_context)

    def has_module_permission(self, request): return not _is_manager(request) and super().has_module_permission(request)
    def has_view_permission(self, request, obj=None): return not _is_manager(request) and super().has_view_permission(request, obj)
    def has_add_permission(self, request): return not _is_manager(request) and super().has_add_permission(request)
    def has_change_permission(self, request, obj=None): return not _is_manager(request) and super().has_change_permission(request, obj)
    def has_delete_permission(self, request, obj=None): return not _is_manager(request) and super().has_delete_permission(request, obj)


# ── System Settings admin ─────────────────────────────────────────────────────

@admin.register(SystemSetting)
class SystemSettingAdmin(admin.ModelAdmin):
    change_form_template = "admin/attendance/systemsetting/change_form.html"

    def has_add_permission(self, request):
        return False  # singleton — created automatically on first get()

    def has_delete_permission(self, request, obj=None):
        return False

    def has_module_permission(self, request):
        return request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def changelist_view(self, request, extra_context=None):
        """Always jump straight to the single settings record."""
        from django.http import HttpResponseRedirect
        obj = SystemSetting.get()
        return HttpResponseRedirect(
            reverse("admin:attendance_systemsetting_change", args=[obj.pk])
        )

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        self.message_user(
            request,
            f"Display timezone updated to: {obj.get_display_timezone_display()}",
            level=messages.SUCCESS,
        )
