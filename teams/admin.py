from django.contrib import admin, messages
from django.core.management import call_command
from django.db import transaction
from django.http import HttpResponseRedirect
from django.urls import path

from accounts.models import EmployeeProfile


def _is_manager(request):
    if request.user.is_superuser:
        return False
    profile = getattr(request.user, "employee_profile", None)
    return bool(profile and profile.role == EmployeeProfile.RoleChoices.MANAGER)

from .forms import TeamAdminForm, TeamMemberInlineForm
from .models import Team, TeamMember


class TeamMemberInline(admin.TabularInline):
    model = TeamMember
    form = TeamMemberInlineForm
    extra = 0
    autocomplete_fields = ("employee",)
    fields = ("employee", "role_in_team", "joined_at", "is_primary")
    show_change_link = False
    template = "admin/teams/team/members_inline.html"

    def has_view_permission(self, request, obj=None):
        if request.user.is_superuser:
            return True
        profile = getattr(request.user, "employee_profile", None)
        return bool(
            profile
            and obj
            and obj.manager_id == profile.pk
            and request.user.has_perm("teams.view_teammember")
        )

    def has_add_permission(self, request, obj=None):
        if request.user.is_superuser:
            return True
        profile = getattr(request.user, "employee_profile", None)
        return bool(
            profile
            and obj
            and obj.manager_id == profile.pk
            and request.user.has_perm("teams.add_teammember")
            and request.user.has_perm("teams.can_manage_owned_teams")
        )

    def has_change_permission(self, request, obj=None):
        if request.user.is_superuser:
            return True
        profile = getattr(request.user, "employee_profile", None)
        return bool(
            profile
            and obj
            and obj.manager_id == profile.pk
            and request.user.has_perm("teams.change_teammember")
            and request.user.has_perm("teams.can_manage_owned_teams")
        )

    def has_delete_permission(self, request, obj=None):
        if request.user.is_superuser:
            return True
        profile = getattr(request.user, "employee_profile", None)
        return bool(
            profile
            and obj
            and obj.manager_id == profile.pk
            and request.user.has_perm("teams.delete_teammember")
            and request.user.has_perm("teams.can_manage_owned_teams")
        )

    def get_formset(self, request, obj=None, **kwargs):
        formset = super().get_formset(request, obj, **kwargs)
        parent_request = request

        class RequestAwareFormSet(formset):
            def _construct_form(self, i, **form_kwargs):
                form_kwargs["request"] = parent_request
                return super()._construct_form(i, **form_kwargs)

        return RequestAwareFormSet


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    form = TeamAdminForm
    inlines = [TeamMemberInline]
    change_list_template = "admin/teams/team/change_list.html"
    change_form_template = "admin/teams/team/change_form.html"
    list_display = (
        "name",
        "code",
        "department",
        "manager",
        "member_count",
        "parent_team",
        "is_active",
    )
    list_filter = ("is_active", "department", "manager", "parent_team")
    search_fields = (
        "name",
        "code",
        "department",
        "manager__full_name",
        "members__employee__full_name",
    )
    autocomplete_fields = ("parent_team",)
    readonly_fields = ("created_by", "created_at", "updated_at", "member_count_display")
    fieldsets = (
        (
            "Team Details",
            {
                "fields": (
                    ("name", "code"),
                    "department",
                    "description",
                    ("manager", "parent_team"),
                    ("is_active", "member_count_display"),
                )
            },
        ),
        (
            "Audit",
            {
                "fields": (("created_by", "created_at"), "updated_at"),
            },
        ),
    )

    def get_queryset(self, request):
        queryset = super().get_queryset(request).select_related(
            "manager",
            "parent_team",
            "created_by",
        )
        if request.user.is_superuser:
            return queryset

        profile = getattr(request.user, "employee_profile", None)
        if profile and profile.role == EmployeeProfile.RoleChoices.MANAGER:
            return queryset.filter(manager=profile)
        return queryset.none()

    def has_view_permission(self, request, obj=None):
        if request.user.is_superuser:
            return True
        profile = getattr(request.user, "employee_profile", None)
        if not profile:
            return False
        if profile.role != EmployeeProfile.RoleChoices.MANAGER:
            return False
        if obj is None:
            return request.user.has_perm("teams.view_team")
        return obj.manager_id == profile.pk and request.user.has_perm("teams.view_team")

    def has_module_permission(self, request):
        if request.user.is_superuser:
            return True
        return request.user.has_perm("teams.view_team")

    def has_add_permission(self, request):
        if request.user.is_superuser:
            return True
        profile = getattr(request.user, "employee_profile", None)
        return bool(
            profile
            and profile.role == EmployeeProfile.RoleChoices.MANAGER
            and request.user.has_perm("teams.add_team")
            and request.user.has_perm("teams.can_create_team")
        )

    def has_change_permission(self, request, obj=None):
        if request.user.is_superuser:
            return True
        profile = getattr(request.user, "employee_profile", None)
        if not profile or profile.role != EmployeeProfile.RoleChoices.MANAGER:
            return False
        if obj is None:
            return request.user.has_perm("teams.change_team") and request.user.has_perm(
                "teams.can_manage_owned_teams"
            )
        return (
            obj.manager_id == profile.pk
            and request.user.has_perm("teams.change_team")
            and request.user.has_perm("teams.can_manage_owned_teams")
        )

    def has_delete_permission(self, request, obj=None):
        if request.user.is_superuser:
            return True
        profile = getattr(request.user, "employee_profile", None)
        if not profile or profile.role != EmployeeProfile.RoleChoices.MANAGER:
            return False
        return bool(
            obj
            and obj.manager_id == profile.pk
            and request.user.has_perm("teams.delete_team")
            and request.user.has_perm("teams.can_manage_owned_teams")
        )

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        parent_request = request

        class RequestAwareForm(form):
            def __init__(self, *args, **inner_kwargs):
                inner_kwargs["request"] = parent_request
                super().__init__(*args, **inner_kwargs)

        return RequestAwareForm

    def get_inline_instances(self, request, obj=None):
        if obj is None:
            return []
        return super().get_inline_instances(request, obj)

    def add_view(self, request, form_url="", extra_context=None):
        try:
            with transaction.atomic():
                return super().add_view(request, form_url, extra_context)
        except Exception as e:
            messages.error(request, f"Could not save team: {e}")
            return HttpResponseRedirect(request.path)

    def change_view(self, request, object_id, form_url="", extra_context=None):
        try:
            with transaction.atomic():
                return super().change_view(request, object_id, form_url, extra_context)
        except Exception as e:
            messages.error(request, f"Could not save team: {e}")
            return HttpResponseRedirect(request.path)

    def save_model(self, request, obj, form, change):
        if not obj.created_by_id:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

    def get_urls(self):
        custom = [
            path(
                "sync-from-departments/",
                self.admin_site.admin_view(self._sync_from_departments_view),
                name="teams_team_sync_departments",
            ),
        ]
        return custom + super().get_urls()

    def _sync_from_departments_view(self, request):
        if not request.user.is_superuser:
            messages.error(request, "Only superusers can run the department sync.")
            return HttpResponseRedirect("../")
        try:
            from io import StringIO
            buf = StringIO()
            call_command("sync_department_teams", stdout=buf)
            output = buf.getvalue()
            for line in output.strip().splitlines():
                if "created" in line.lower() or "complete" in line.lower():
                    messages.success(request, line)
                elif "skipped" in line.lower() or "warning" in line.lower():
                    messages.warning(request, line)
                else:
                    messages.info(request, line)
        except Exception as exc:
            messages.error(request, f"Sync failed: {exc}")
        return HttpResponseRedirect("../")

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        qs = self.get_queryset(request)
        extra_context["tm_total"] = qs.count()
        extra_context["tm_active"] = qs.filter(is_active=True).count()
        extra_context["tm_inactive"] = qs.filter(is_active=False).count()
        from teams.models import TeamMember
        extra_context["tm_members"] = TeamMember.objects.count()
        extra_context["sync_url"] = "sync-from-departments/"
        return super().changelist_view(request, extra_context=extra_context)

    @admin.display(description="Members")
    def member_count_display(self, obj):
        if not obj.pk:
            return 0
        return obj.member_count


@admin.register(TeamMember)
class TeamMemberAdmin(admin.ModelAdmin):
    form = TeamMemberInlineForm
    change_list_template = "admin/teams/teammember/change_list.html"
    change_form_template = "admin/teams/teammember/change_form.html"
    list_display = ("employee", "team", "role_in_team", "joined_at", "is_primary")
    list_filter = ("role_in_team", "is_primary", "team")
    search_fields = ("employee__full_name", "team__name", "team__code")
    autocomplete_fields = ("team", "employee")
    fieldsets = (
        (None, {
            "fields": (
                ("team", "employee"),
                ("role_in_team", "joined_at"),
                "is_primary",
            )
        }),
    )

    def get_queryset(self, request):
        queryset = super().get_queryset(request).select_related("team", "employee")
        if request.user.is_superuser:
            return queryset
        profile = getattr(request.user, "employee_profile", None)
        if profile and profile.role == EmployeeProfile.RoleChoices.MANAGER:
            return queryset.filter(team__manager=profile)
        return queryset.none()

    def has_module_permission(self, request):
        if request.user.is_superuser:
            return True
        profile = getattr(request.user, "employee_profile", None)
        return bool(
            profile
            and profile.role == EmployeeProfile.RoleChoices.MANAGER
            and request.user.has_perm("teams.view_teammember")
        )

    def has_view_permission(self, request, obj=None):
        return self.has_module_permission(request)

    def has_add_permission(self, request):
        if request.user.is_superuser:
            return True
        profile = getattr(request.user, "employee_profile", None)
        return bool(
            profile
            and profile.role == EmployeeProfile.RoleChoices.MANAGER
            and request.user.has_perm("teams.add_teammember")
            and request.user.has_perm("teams.can_manage_owned_teams")
        )

    def has_change_permission(self, request, obj=None):
        if request.user.is_superuser:
            return True
        profile = getattr(request.user, "employee_profile", None)
        if not profile or profile.role != EmployeeProfile.RoleChoices.MANAGER:
            return False
        if obj is None:
            return request.user.has_perm("teams.change_teammember") and request.user.has_perm(
                "teams.can_manage_owned_teams"
            )
        return (
            obj.team.manager_id == profile.pk
            and request.user.has_perm("teams.change_teammember")
            and request.user.has_perm("teams.can_manage_owned_teams")
        )

    def has_delete_permission(self, request, obj=None):
        if request.user.is_superuser:
            return True
        profile = getattr(request.user, "employee_profile", None)
        if not profile or profile.role != EmployeeProfile.RoleChoices.MANAGER:
            return False
        return bool(
            obj
            and obj.team.manager_id == profile.pk
            and request.user.has_perm("teams.delete_teammember")
            and request.user.has_perm("teams.can_manage_owned_teams")
        )

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        qs = self.get_queryset(request)
        extra_context["tmm_total"] = qs.count()
        extra_context["tmm_leads"] = qs.filter(role_in_team=TeamMember.TeamRoleChoices.LEAD).count()
        extra_context["tmm_coordinators"] = qs.filter(role_in_team=TeamMember.TeamRoleChoices.COORDINATOR).count()
        extra_context["tmm_primary"] = qs.filter(is_primary=True).count()
        return super().changelist_view(request, extra_context=extra_context)

    def change_view(self, request, object_id, form_url="", extra_context=None):
        extra_context = extra_context or {}
        try:
            obj = self.get_queryset(request).get(pk=object_id)
            emp = obj.employee
            from attendance.models import AttendanceRecord
            from leaves.models import LeaveAllocation
            extra_context["attendance_records"] = (
                AttendanceRecord.objects.filter(employee=emp).order_by("-date")[:30]
            )
            extra_context["leave_allocs"] = (
                LeaveAllocation.objects.filter(employee=emp).select_related("leave_type").order_by("leave_type__name")
            )
            from salary.models import SalarySetup, Payslip
            sal = SalarySetup.objects.filter(employee=emp, is_active=True).order_by("-created_at").first()
            if sal:
                basic    = sal.basic_salary or 0
                hra      = sal.house_rent_allowance or 0
                ca       = sal.conveyance_allowance or 0
                ma       = sal.medical_allowance or 0
                oa       = sal.other_allowance or 0
                ua       = sal.utility_allowance or 0
                pay_mode = sal.payment_mode
                total_deductions = (
                    (sal.eobi_contribution or 0)
                    + (sal.pessi_contribution or 0)
                    + (sal.loan_installment or 0)
                    + (sal.advance_salary_repayment or 0)
                    + (sal.provident_fund_deduction or 0)
                    + (sal.misc_deduction or 0)
                )
            else:
                basic    = emp.basic_salary or 0
                hra      = emp.house_rent_allowance or 0
                ca       = emp.conveyance_allowance or 0
                ma       = emp.medical_allowance or 0
                oa       = emp.other_allowance or 0
                ua       = 0
                pay_mode = emp.payment_mode
                total_deductions = 0
            allowances = hra + ca + ma + oa + ua
            gross      = basic + allowances
            # prefer latest payslip for tax & net if available
            payslip = Payslip.objects.filter(employee=emp).order_by("-created_at").first()
            if payslip:
                income_tax = payslip.income_tax or 0
                net_salary = payslip.net_salary or 0
            else:
                income_tax = 0
                net_salary = max(gross - total_deductions, 0)
            extra_context["sal_basic"]         = basic
            extra_context["sal_hra"]           = hra
            extra_context["sal_ca"]            = ca
            extra_context["sal_ma"]            = ma
            extra_context["sal_oa"]            = oa
            extra_context["sal_ua"]            = ua
            extra_context["sal_pay_mode"]      = pay_mode
            extra_context["sal_deductions"]    = total_deductions
            extra_context["sal_income_tax"]    = income_tax
            extra_context["allowances_total"]  = allowances
            extra_context["salary_total"]      = gross
            extra_context["sal_net"]           = net_salary
        except self.model.DoesNotExist:
            pass
        return super().change_view(request, object_id, form_url, extra_context)

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        parent_request = request

        class RequestAwareForm(form):
            def __init__(self, *args, **inner_kwargs):
                inner_kwargs["request"] = parent_request
                super().__init__(*args, **inner_kwargs)

        return RequestAwareForm
