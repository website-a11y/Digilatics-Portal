import calendar
from datetime import date, timedelta

from django.contrib import admin, messages
from django.contrib.admin import display
from django.db.models import Count, Q, Sum
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import path, reverse
from django.utils.html import format_html

from accounts.models import EmployeeProfile
from .forms import BulkAllocationForm, LeaveAllocationAdminForm, LeaveRequestAdminForm
from .models import LeaveAllocation, LeaveRequest, LeaveType


def _is_manager(request):
    if request.user.is_superuser:
        return False
    profile = getattr(request.user, "employee_profile", None)
    return bool(profile and profile.role == EmployeeProfile.RoleChoices.MANAGER)


# ── Leave Type ────────────────────────────────────────────────────────────────

@admin.register(LeaveType)
class LeaveTypeAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "default_days_display",
        "is_paid_display",
        "available_for_probation_display",
        "requires_attachment_display",
        "is_active_display",
    )
    list_filter = ("is_paid", "available_for_probation", "requires_attachment", "is_active")
    search_fields = ("name",)

    @display(description="Days")
    def default_days_display(self, obj):
        return format_html(
            '<span style="background:#f0f9ff;color:#0369a1;border:1px solid #bae6fd;'
            'border-radius:6px;padding:2px 10px;font-size:12px;font-weight:700;">'
            '{} days</span>',
            obj.default_days,
        )

    @display(description="Type")
    def is_paid_display(self, obj):
        return "Paid" if obj.is_paid else "Unpaid"

    @display(description="Probation")
    def available_for_probation_display(self, obj):
        return "Allowed" if obj.available_for_probation else "Excluded"

    @display(description="Attachment")
    def requires_attachment_display(self, obj):
        return "Required" if obj.requires_attachment else "Optional"

    @display(description="Status")
    def is_active_display(self, obj):
        return "Active" if obj.is_active else "Inactive"

    def has_module_permission(self, request): return not _is_manager(request) and super().has_module_permission(request)
    def has_view_permission(self, request, obj=None): return not _is_manager(request) and super().has_view_permission(request, obj)
    def has_add_permission(self, request): return not _is_manager(request) and super().has_add_permission(request)
    def has_change_permission(self, request, obj=None): return not _is_manager(request) and super().has_change_permission(request, obj)
    def has_delete_permission(self, request, obj=None): return not _is_manager(request) and super().has_delete_permission(request, obj)


# ── Leave Allocation ──────────────────────────────────────────────────────────

@admin.register(LeaveAllocation)
class LeaveAllocationAdmin(admin.ModelAdmin):
    form = LeaveAllocationAdminForm
    list_display = (
        "employee",
        "leave_type",
        "year",
        "allocated_days",
        "utilization_bar",
    )
    list_filter = ("year", "leave_type")
    search_fields = ("employee__full_name", "employee__employee_code", "leave_type__name")
    autocomplete_fields = ("employee", "leave_type")
    readonly_fields = ("booked_days_display", "remaining_days_display")
    change_list_template = "admin/leaves/leaveallocation/change_list.html"
    fieldsets = (
        (
            "Allocation",
            {
                "fields": (
                    ("employee", "leave_type"),
                    ("year", "allocated_days"),
                    "carry_forward_days",
                    "notes",
                )
            },
        ),
        (
            "Balance",
            {
                "fields": (("booked_days_display", "remaining_days_display"),),
            },
        ),
    )

    def get_urls(self):
        from django.urls import path
        urls = super().get_urls()
        return [
            path(
                "bulk-assign/",
                self.admin_site.admin_view(self.bulk_assign_view),
                name="leaves_leaveallocation_bulk_assign",
            )
        ] + urls

    def get_queryset(self, request):
        queryset = super().get_queryset(request).select_related("employee", "leave_type")
        if request.user.is_superuser:
            return queryset
        profile = getattr(request.user, "employee_profile", None)
        if profile and profile.role == EmployeeProfile.RoleChoices.MANAGER:
            return queryset.filter(employee__reporting_manager=profile)
        return queryset.none()

    def has_module_permission(self, request):
        if _is_manager(request):
            return False
        return request.user.is_staff or request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return self.has_module_permission(request)

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    def bulk_assign_view(self, request):
        if not request.user.is_superuser:
            self.message_user(request, "Only admins can bulk assign leave allocations.", level=messages.ERROR)
            return redirect("admin:leaves_leaveallocation_changelist")

        if request.method == "POST":
            form = BulkAllocationForm(request.POST)
            if form.is_valid():
                count = form.save()
                self.message_user(
                    request,
                    f"Leave allocation created or updated for {count} active employees.",
                    level=messages.SUCCESS,
                )
                return redirect("admin:leaves_leaveallocation_changelist")
        else:
            form = BulkAllocationForm()

        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "title": "Bulk Assign Leave Allocation",
            "form": form,
        }
        return render(request, "admin/leaves/leaveallocation/bulk_assign.html", context)

    @display(description="Utilization")
    def utilization_bar(self, obj):
        total = float(obj.total_available_days or 0)
        booked = float(obj.booked_days or 0)
        remaining = float(obj.remaining_days or 0)
        if total == 0:
            pct = 0
        else:
            pct = min(round(booked / total * 100), 100)

        if pct >= 90:
            bar_color = "#ef4444"
            track_color = "#fee2e2"
        elif pct >= 60:
            bar_color = "#f59e0b"
            track_color = "#e8eaf6"
        else:
            bar_color = "#22c55e"
            track_color = "#dcfce7"

        return format_html(
            '<div style="min-width:130px">'
            '  <div style="background:{track};border-radius:999px;height:7px;overflow:hidden;margin-bottom:4px">'
            '    <div style="background:{bar};width:{pct}%;height:100%;border-radius:999px;'
            '         transition:width .3s"></div>'
            '  </div>'
            '  <div style="font-size:11px;color:#64748b;display:flex;justify-content:space-between">'
            '    <span>{booked}d used</span><span style="font-weight:700;color:{bar}">{remaining}d left</span>'
            '  </div>'
            '</div>',
            track=track_color, bar=bar_color, pct=pct,
            booked=booked, remaining=remaining,
        )

    @display(description="Booked")
    def booked_days_display(self, obj):
        return obj.booked_days if obj.pk else 0

    @display(description="Remaining")
    def remaining_days_display(self, obj):
        return obj.remaining_days if obj.pk else 0


# ── Leave Request ─────────────────────────────────────────────────────────────

@admin.register(LeaveRequest)
class LeaveRequestAdmin(admin.ModelAdmin):
    change_list_template = "admin/leaves/leaverequest/change_list.html"
    change_form_template = "admin/leaves/leaverequest/change_form.html"
    form = LeaveRequestAdminForm
    list_display = (
        "employee",
        "leave_type",
        "date_range",
        "number_of_days",
        "status_badge",
        "balance_bar",
    )
    list_filter = ("status", "leave_type", "from_date")
    search_fields = ("employee__full_name", "employee__employee_code", "reason")
    autocomplete_fields = ("employee", "leave_type", "allocation", "created_by", "manager_approved_by", "approved_by")
    readonly_fields = ("allocation_balance", "created_at", "updated_at")

    fieldsets = (
        (
            "Leave Request",
            {
                "fields": (
                    ("employee", "leave_type"),
                    ("from_date", "to_date"),
                    ("number_of_days", "status"),
                    "attachment",
                    "reason",
                    "remarks",
                    "allocation_balance",
                )
            },
        ),
        (
            "Audit",
            {
                "fields": (
                    ("allocation", "created_by"),
                    ("manager_approved_by", "approved_by"),
                    ("created_at", "updated_at"),
                ),
            },
        ),
    )
    actions = ("approve_requests", "reject_requests")

    # ── Custom URLs ───────────────────────────────────────────────────────────

    def get_urls(self):
        urls = super().get_urls()
        return [
            path(
                "detail/<int:pk>/",
                self.admin_site.admin_view(self.leave_detail_json),
                name="leaves_leaverequest_detail_json",
            ),
            path(
                "<int:pk>/approve/",
                self.admin_site.admin_view(self.approve_request_row),
                name="leaves_leaverequest_approve_row",
            ),
            path(
                "<int:pk>/reject/",
                self.admin_site.admin_view(self.reject_request_row),
                name="leaves_leaverequest_reject_row",
            ),
        ] + urls

    def leave_detail_json(self, request, pk):
        try:
            lr = (
                LeaveRequest.objects
                .select_related("employee", "leave_type", "allocation", "approved_by", "created_by")
                .get(pk=pk)
            )
        except LeaveRequest.DoesNotExist:
            return JsonResponse({"error": "Not found"}, status=404)

        if not self.has_view_permission(request, lr):
            return JsonResponse({"error": "Permission denied"}, status=403)

        allocation = lr.allocation
        data = {
            "pk": lr.pk,
            "employee_name": lr.employee.full_name,
            "employee_code": lr.employee.employee_code,
            "department": lr.employee.department or "",
            "avatar_url": lr.employee.profile_photo.url if lr.employee.profile_photo else "",
            "leave_type": lr.leave_type.name,
            "is_paid": lr.leave_type.is_paid,
            "from_date": lr.from_date.strftime("%d %b %Y"),
            "to_date": lr.to_date.strftime("%d %b %Y"),
            "number_of_days": str(lr.number_of_days),
            "status": lr.status,
            "reason": lr.reason or "",
            "remarks": lr.remarks or "",
            "created_at": lr.created_at.strftime("%d %b %Y, %H:%M") if lr.created_at else "",
            "approved_by": lr.approved_by.full_name if lr.approved_by else "",
            "allocation_total": str(allocation.total_available_days) if allocation else "N/A",
            "allocation_booked": str(allocation.booked_days) if allocation else "N/A",
            "allocation_remaining": str(allocation.remaining_days) if allocation else "N/A",
            "change_url": reverse("admin:leaves_leaverequest_change", args=[pk]),
            "approve_url": reverse("admin:leaves_leaverequest_approve_row", args=[pk]),
            "reject_url": reverse("admin:leaves_leaverequest_reject_row", args=[pk]),
        }
        return JsonResponse(data)

    # ── Queryset / permissions ────────────────────────────────────────────────

    def get_queryset(self, request):
        queryset = super().get_queryset(request).select_related(
            "employee", "leave_type", "allocation", "created_by", "approved_by",
        )
        if request.user.is_superuser:
            return queryset
        profile = getattr(request.user, "employee_profile", None)
        if not profile:
            return queryset.none()
        if profile.role in [EmployeeProfile.RoleChoices.MANAGER, EmployeeProfile.RoleChoices.APPROVER]:
            return queryset.filter(employee__reporting_manager=profile) | queryset.filter(employee=profile)
        return queryset.filter(employee=profile)

    def has_module_permission(self, request):
        return request.user.is_staff or request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return self.has_module_permission(request)

    def has_add_permission(self, request):
        return request.user.is_staff or request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        if request.user.is_superuser:
            return True
        profile = getattr(request.user, "employee_profile", None)
        if not profile:
            return False
        if profile.role in [EmployeeProfile.RoleChoices.MANAGER, EmployeeProfile.RoleChoices.APPROVER]:
            return obj is None or obj.employee_id == profile.pk or obj.employee.reporting_manager_id == profile.pk
        return obj is None or obj.employee_id == profile.pk

    def has_delete_permission(self, request, obj=None):
        return self.has_change_permission(request, obj)

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        parent_request = request

        class RequestAwareForm(form):
            def __init__(self, *args, **inner_kwargs):
                inner_kwargs["request"] = parent_request
                super().__init__(*args, **inner_kwargs)

        return RequestAwareForm

    def save_model(self, request, obj, form, change):
        profile = getattr(request.user, "employee_profile", None)
        if not obj.created_by_id and profile:
            obj.created_by = profile
        if obj.status == LeaveRequest.StatusChoices.MANAGER_APPROVED and not obj.manager_approved_by_id and profile:
            obj.manager_approved_by = profile
        if obj.status == LeaveRequest.StatusChoices.APPROVED and profile:
            obj.approved_by = profile
        super().save_model(request, obj, form, change)

    # ── changelist_view — inject dashboard data ──────────────────────────────

    def changelist_view(self, request, extra_context=None):
        today = date.today()
        qs = self.get_queryset(request)

        # ── Resolve selected period ───────────────────────────────────────────
        view_mode = request.GET.get("lrview", "month")
        filter_date_str = request.GET.get("lrdate", "")
        filter_month_str = request.GET.get("lrmonth", "")

        if view_mode == "day":
            try:
                pd = date.fromisoformat(filter_date_str) if filter_date_str else today
            except ValueError:
                pd = today
            period_start = pd
            period_end = pd
            period_label = pd.strftime("%d %B %Y")
            filter_date_val = pd.strftime("%Y-%m-%d")
            filter_month_val = ""

        elif view_mode == "week":
            try:
                pd = date.fromisoformat(filter_date_str) if filter_date_str else today
            except ValueError:
                pd = today
            period_start = pd - timedelta(days=pd.weekday())   # Monday
            period_end = period_start + timedelta(days=6)       # Sunday
            period_label = (
                f"{period_start.strftime('%d %b')} – {period_end.strftime('%d %b %Y')}"
            )
            filter_date_val = pd.strftime("%Y-%m-%d")
            filter_month_val = ""

        else:  # month (default)
            view_mode = "month"
            try:
                if filter_month_str:
                    yr_m, mo_m = filter_month_str.split("-")
                    pm = date(int(yr_m), int(mo_m), 1)
                else:
                    pm = today.replace(day=1)
            except (ValueError, TypeError):
                pm = today.replace(day=1)
            period_start = pm
            last_day = calendar.monthrange(pm.year, pm.month)[1]
            period_end = pm.replace(day=last_day)
            period_label = pm.strftime("%B %Y")
            filter_date_val = ""
            filter_month_val = pm.strftime("%Y-%m")

        # ── Period-scoped stats ───────────────────────────────────────────────
        # Approved/rejected whose *start date* falls in the period
        period_qs = qs.filter(from_date__gte=period_start, from_date__lte=period_end)
        approved_period = period_qs.filter(
            status=LeaveRequest.StatusChoices.APPROVED
        ).count()
        rejected_period = period_qs.filter(
            status=LeaveRequest.StatusChoices.REJECTED
        ).count()
        days_period = period_qs.filter(
            status=LeaveRequest.StatusChoices.APPROVED
        ).aggregate(t=Sum("number_of_days"))["t"] or 0

        # People on leave *during* the period (overlapping range)
        on_leave_period_qs = qs.filter(
            status=LeaveRequest.StatusChoices.APPROVED,
            from_date__lte=period_end,
            to_date__gte=period_start,
        ).select_related("employee", "leave_type")
        on_leave_period_count = on_leave_period_qs.count()
        on_leave_list = list(on_leave_period_qs[:8])

        # ── Global stats (not period-scoped) ─────────────────────────────────
        pending_count = qs.filter(status=LeaveRequest.StatusChoices.PENDING).count()

        pending_list = list(
            qs.filter(status=LeaveRequest.StatusChoices.PENDING)
            .select_related("employee", "leave_type")
            .order_by("from_date")[:10]
        )

        # ── Monthly breakdown — last 6 months (always global) ────────────────
        monthly_rows = []
        yr, mo = today.year, today.month
        for _ in range(6):
            apm = qs.filter(
                status=LeaveRequest.StatusChoices.APPROVED,
                from_date__year=yr, from_date__month=mo,
            ).count()
            dpm = qs.filter(
                status=LeaveRequest.StatusChoices.APPROVED,
                from_date__year=yr, from_date__month=mo,
            ).aggregate(t=Sum("number_of_days"))["t"] or 0
            rpm = qs.filter(
                status=LeaveRequest.StatusChoices.REJECTED,
                from_date__year=yr, from_date__month=mo,
            ).count()
            ppm = qs.filter(
                status=LeaveRequest.StatusChoices.PENDING,
                from_date__year=yr, from_date__month=mo,
            ).count()
            monthly_rows.insert(0, {
                "label": date(yr, mo, 1).strftime("%b %Y"),
                "approved": apm, "days": dpm,
                "rejected": rpm, "pending": ppm,
                "is_current": yr == today.year and mo == today.month,
            })
            mo -= 1
            if mo == 0:
                mo = 12
                yr -= 1

        # ── Yearly breakdown — last 3 years (always global) ──────────────────
        yearly_rows = []
        for yr_offset in range(2, -1, -1):
            yr_val = today.year - yr_offset
            apy = qs.filter(
                status=LeaveRequest.StatusChoices.APPROVED,
                from_date__year=yr_val,
            ).count()
            dpy = qs.filter(
                status=LeaveRequest.StatusChoices.APPROVED,
                from_date__year=yr_val,
            ).aggregate(t=Sum("number_of_days"))["t"] or 0
            rpy = qs.filter(
                status=LeaveRequest.StatusChoices.REJECTED,
                from_date__year=yr_val,
            ).count()
            tpy = qs.filter(from_date__year=yr_val).count()
            yearly_rows.append({
                "label": str(yr_val),
                "approved": apy, "days": dpy,
                "rejected": rpy, "total": tpy,
                "is_current": yr_val == today.year,
            })

        extra_context = extra_context or {}
        extra_context.update({
            # Filter state
            "view_mode": view_mode,
            "filter_date_val": filter_date_val,
            "filter_month_val": filter_month_val,
            "period_label": period_label,
            # KPI cards (period-scoped)
            "kpi_pending": pending_count,
            "kpi_on_leave_today": on_leave_period_count,
            "kpi_approved_month": approved_period,
            "kpi_days_month": days_period,
            "kpi_rejected_month": rejected_period,
            "kpi_month_label": period_label,
            "kpi_today_label": today.strftime("%d %b %Y"),
            # Lists
            "on_leave_today_list": on_leave_list,
            "pending_list": pending_list,
            # Breakdown tables
            "monthly_rows": monthly_rows,
            "yearly_rows": yearly_rows,
        })

        # Strip our custom GET params before handing off to Django's
        # changelist machinery — otherwise ChangeList tries to apply lrview,
        # lrdate, lrmonth as queryset filters, finds no such fields, and raises
        # IncorrectLookupParameters (shown as the "database installation" error).
        _original_get = request.GET
        try:
            _clean = request.GET.copy()
            for _k in ("lrview", "lrdate", "lrmonth"):
                _clean.pop(_k, None)
            request.GET = _clean
            return super().changelist_view(request, extra_context=extra_context)
        finally:
            request.GET = _original_get

    # ── Row actions ───────────────────────────────────────────────────────────

    def _is_admin_level(self, request):
        """Superusers and staff with no employee profile, or APPROVER role, act as final approvers."""
        if request.user.is_superuser:
            return True
        profile = getattr(request.user, "employee_profile", None)
        if not profile:
            return True
        return profile.role == EmployeeProfile.RoleChoices.APPROVER

    def approve_request_row(self, request, pk):
        from attendance.services import sync_leave_request_to_attendance
        try:
            lr = LeaveRequest.objects.select_related("employee", "leave_type").get(pk=pk)
        except LeaveRequest.DoesNotExist:
            self.message_user(request, "Leave request not found.", level=messages.ERROR)
            return redirect(reverse("admin:leaves_leaverequest_changelist"))

        profile = getattr(request.user, "employee_profile", None)
        is_admin = self._is_admin_level(request)

        if is_admin:
            # Admin: moves Manager Approved → Approved (or Pending → Approved as override)
            if lr.status in (LeaveRequest.StatusChoices.MANAGER_APPROVED, LeaveRequest.StatusChoices.PENDING):
                lr.status = LeaveRequest.StatusChoices.APPROVED
                lr.approved_by = profile
                lr.save()
                sync_leave_request_to_attendance(lr)
                self.message_user(
                    request,
                    f"Leave request for {lr.employee.full_name} fully approved.",
                    level=messages.SUCCESS,
                )
            else:
                self.message_user(
                    request,
                    f"Cannot approve — current status: {lr.status}.",
                    level=messages.WARNING,
                )
        else:
            # Manager: moves Pending → Manager Approved
            if lr.status == LeaveRequest.StatusChoices.PENDING:
                lr.status = LeaveRequest.StatusChoices.MANAGER_APPROVED
                lr.manager_approved_by = profile
                lr.save()
                self.message_user(
                    request,
                    f"Leave request for {lr.employee.full_name} approved by manager — awaiting HR/Admin approval.",
                    level=messages.SUCCESS,
                )
            else:
                self.message_user(
                    request,
                    f"Managers can only approve Pending requests (current status: {lr.status}).",
                    level=messages.WARNING,
                )
        return redirect(reverse("admin:leaves_leaverequest_changelist"))

    def reject_request_row(self, request, pk):
        from attendance.services import sync_leave_request_to_attendance
        try:
            lr = LeaveRequest.objects.select_related("employee", "leave_type").get(pk=pk)
        except LeaveRequest.DoesNotExist:
            self.message_user(request, "Leave request not found.", level=messages.ERROR)
            return redirect(reverse("admin:leaves_leaverequest_changelist"))

        rejectable = (
            LeaveRequest.StatusChoices.PENDING,
            LeaveRequest.StatusChoices.MANAGER_APPROVED,
        )
        if lr.status in rejectable:
            lr.status = LeaveRequest.StatusChoices.REJECTED
            lr.save()
            sync_leave_request_to_attendance(lr)
            self.message_user(
                request,
                f"Leave request for {lr.employee.full_name} rejected.",
                level=messages.WARNING,
            )
        else:
            self.message_user(
                request,
                f"Cannot reject — current status: {lr.status}.",
                level=messages.WARNING,
            )
        return redirect(reverse("admin:leaves_leaverequest_changelist"))

    # ── Bulk actions ──────────────────────────────────────────────────────────

    @admin.action(description="Approve selected leave requests")
    def approve_requests(self, request, queryset):
        from attendance.services import sync_leave_request_to_attendance
        profile = getattr(request.user, "employee_profile", None)
        is_admin = self._is_admin_level(request)

        if is_admin:
            # Admin: fully approve Manager Approved (and Pending as override)
            eligible = queryset.filter(
                status__in=[LeaveRequest.StatusChoices.MANAGER_APPROVED, LeaveRequest.StatusChoices.PENDING]
            )
            leave_requests = list(eligible.select_related("employee", "leave_type"))
            updated = eligible.update(status=LeaveRequest.StatusChoices.APPROVED, approved_by=profile)
            for lr in leave_requests:
                lr.status = LeaveRequest.StatusChoices.APPROVED
                sync_leave_request_to_attendance(lr)
            self.message_user(request, f"{updated} leave request(s) fully approved.", level=messages.SUCCESS)
        else:
            # Manager: move Pending → Manager Approved
            eligible = queryset.filter(status=LeaveRequest.StatusChoices.PENDING)
            updated = eligible.update(
                status=LeaveRequest.StatusChoices.MANAGER_APPROVED,
                manager_approved_by=profile,
            )
            self.message_user(
                request,
                f"{updated} leave request(s) approved by manager — awaiting HR/Admin final approval.",
                level=messages.SUCCESS,
            )

    @admin.action(description="Reject selected leave requests")
    def reject_requests(self, request, queryset):
        from attendance.services import sync_leave_request_to_attendance
        eligible = queryset.filter(
            status__in=[LeaveRequest.StatusChoices.PENDING, LeaveRequest.StatusChoices.MANAGER_APPROVED]
        )
        leave_requests = list(eligible.select_related("employee", "leave_type"))
        updated = eligible.update(status=LeaveRequest.StatusChoices.REJECTED)
        for lr in leave_requests:
            lr.status = LeaveRequest.StatusChoices.REJECTED
            sync_leave_request_to_attendance(lr)
        self.message_user(request, f"{updated} leave request(s) rejected.", level=messages.SUCCESS)

    # ── Display columns ───────────────────────────────────────────────────────

    @display(description="Period")
    def date_range(self, obj):
        return format_html(
            '<span style="white-space:nowrap;font-size:13px;">'
            '<strong>{}</strong>'
            '<span style="color:#94a3b8;margin:0 5px">→</span>'
            '<strong>{}</strong>'
            '</span>',
            obj.from_date.strftime("%d %b %Y"),
            obj.to_date.strftime("%d %b %Y"),
        )

    @display(description="Status")
    def status_badge(self, obj):
        status_text = dict(LeaveRequest.StatusChoices.choices).get(obj.status, obj.status)
        return status_text

    @display(description="Balance")
    def balance_bar(self, obj):
        if not obj.allocation_id:
            return format_html('<span style="color:#94a3b8;font-size:12px;">No allocation</span>')

        total = float(obj.allocation.total_available_days or 0)
        booked = float(obj.allocation.booked_days or 0)
        remaining = float(obj.allocation.remaining_days or 0)

        if total == 0:
            pct = 0
        else:
            pct = min(round(booked / total * 100), 100)

        if pct >= 90:
            bar_color, track_color = "#ef4444", "#fee2e2"
        elif pct >= 60:
            bar_color, track_color = "#f59e0b", "#e8eaf6"
        else:
            bar_color, track_color = "#22c55e", "#dcfce7"

        return format_html(
            '<div style="min-width:120px">'
            '  <div style="background:{track};border-radius:999px;height:6px;overflow:hidden;margin-bottom:4px">'
            '    <div style="background:{bar};width:{pct}%;height:100%;border-radius:999px"></div>'
            '  </div>'
            '  <div style="font-size:11px;color:#64748b;display:flex;justify-content:space-between">'
            '    <span>{booked}/{total}d</span>'
            '    <span style="font-weight:700;color:{bar}">{remaining}d left</span>'
            '  </div>'
            '</div>',
            track=track_color, bar=bar_color, pct=pct,
            booked=int(booked) if booked == int(booked) else booked,
            total=int(total) if total == int(total) else total,
            remaining=int(remaining) if remaining == int(remaining) else remaining,
        )

    @display(description="Balance")
    def allocation_balance(self, obj):
        """Used in the change form fieldset."""
        if not obj.allocation_id:
            return "No allocation linked"
        return format_html(
            "Available: <strong>{}</strong> &nbsp;|&nbsp; "
            "Booked: <strong>{}</strong> &nbsp;|&nbsp; "
            "Remaining: <strong>{}</strong>",
            obj.allocation.total_available_days,
            obj.allocation.booked_days,
            obj.allocation.remaining_days,
        )
