import calendar as _calendar
from datetime import date
from decimal import Decimal

from django.contrib import admin, messages
from django.contrib.admin import action, display
from django.db.models import Sum
from django.shortcuts import redirect, render
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html

from accounts.models import EmployeeProfile

from .models import (
    PayrollRun, Payslip, SalaryRevision,
    SalarySetup, SalaryTaxSlab, StatutoryDeductionPolicy, TaxYear,
)
from .services import calculate_salary_setup_breakdown, generate_payslips


def _is_manager(request):
    """True when the logged-in user is a Manager (not a superuser)."""
    if request.user.is_superuser:
        return False
    profile = getattr(request.user, "employee_profile", None)
    return bool(profile and profile.role == EmployeeProfile.RoleChoices.MANAGER)


# ══════════════════════════════════════════════════════════════════════════════
# TAX YEAR  +  TAX SLAB (inline)
# ══════════════════════════════════════════════════════════════════════════════

class SalaryTaxSlabInline(admin.TabularInline):
    model = SalaryTaxSlab
    extra = 1
    fields = (
        "name",
        "annual_min_income", "annual_max_income",
        "taxable_excess_over", "base_tax", "rate_percent",
        "sort_order",
    )
    ordering = ("sort_order", "annual_min_income")


@admin.register(TaxYear)
class TaxYearAdmin(admin.ModelAdmin):
    change_list_template = "admin/salary/taxyear/change_list.html"
    change_form_template = "admin/salary/taxyear/change_form.html"
    inlines = [SalaryTaxSlabInline]
    list_display = (
        "fiscal_year", "effective_period", "slab_count",
        "is_active_display",
    )
    list_filter = ("is_active",)
    search_fields = ("fiscal_year",)
    fieldsets = ((
        "Tax Year", {"fields": (
            "fiscal_year",
            ("effective_from", "effective_to"),
            "is_active",
            "notes",
        )},
    ),)

    @display(description="Effective Period")
    def effective_period(self, obj):
        if obj.effective_to:
            return format_html(
                '<span class="sl-period">{} → {}</span>',
                obj.effective_from.strftime("%d %b %Y"),
                obj.effective_to.strftime("%d %b %Y"),
            )
        return format_html(
            '<span class="sl-period">{} <em class="sl-and-above">onwards</em></span>',
            obj.effective_from.strftime("%d %b %Y"),
        )

    @display(description="Slabs")
    def slab_count(self, obj):
        c = obj.slabs.count()
        return format_html('<strong>{}</strong>', c) if c else format_html('<span class="sl-muted">0</span>')

    @display(description="Status")
    def is_active_display(self, obj):
        return "Active" if obj.is_active else "Inactive"

    def has_module_permission(self, request): return not _is_manager(request) and super().has_module_permission(request)
    def has_view_permission(self, request, obj=None): return not _is_manager(request) and super().has_view_permission(request, obj)
    def has_add_permission(self, request): return not _is_manager(request) and super().has_add_permission(request)
    def has_change_permission(self, request, obj=None): return not _is_manager(request) and super().has_change_permission(request, obj)
    def has_delete_permission(self, request, obj=None): return not _is_manager(request) and super().has_delete_permission(request, obj)


# ══════════════════════════════════════════════════════════════════════════════
# STATUTORY DEDUCTION POLICY
# ══════════════════════════════════════════════════════════════════════════════

@admin.register(StatutoryDeductionPolicy)
class StatutoryDeductionPolicyAdmin(admin.ModelAdmin):
    change_list_template = "admin/salary/statutorydeductionpolicy/change_list.html"
    change_form_template = "admin/salary/statutorydeductionpolicy/change_form.html"
    list_display = (
        "name", "effective_period", "eobi_display",
        "pf_employee_display", "pf_employer_display",
        "social_security_display", "is_active_display",
    )
    list_filter = ("is_active",)
    search_fields = ("name",)
    fieldsets = (
        ("Policy Details", {"fields": (
            "name", ("effective_from", "effective_to"), "is_active",
        )}),
        ("Statutory Rates", {
            "fields": (
                ("eobi_employee_fixed", "social_security_fixed"),
                ("provident_fund_employee_percent", "provident_fund_employer_percent"),
                "other_statutory_fixed",
            ),
            "description": "EOBI and Social Security are fixed monthly amounts. "
                           "Provident Fund is a percentage of basic salary.",
        }),
        ("Notes", {"fields": ("notes",)}),
    )

    @display(description="Effective Period")
    def effective_period(self, obj):
        if obj.effective_to:
            return format_html('<span class="sl-period">{} → {}</span>',
                obj.effective_from.strftime("%d %b %Y"),
                obj.effective_to.strftime("%d %b %Y"))
        return format_html('<span class="sl-period">{} <em class="sl-and-above">onwards</em></span>',
            obj.effective_from.strftime("%d %b %Y"))

    @display(description="EOBI (Emp.)")
    def eobi_display(self, obj):
        return format_html('<span class="sl-stat-amt">PKR {}</span>', format(float(obj.eobi_employee_fixed or 0), ",.0f"))

    @display(description="PF Employee %")
    def pf_employee_display(self, obj):
        return format_html('<span class="sl-stat-pct">{}</span>', format(float(obj.provident_fund_employee_percent or 0), ".1f") + "%")

    @display(description="PF Employer %")
    def pf_employer_display(self, obj):
        return format_html('<span class="sl-stat-pct">{}</span>', format(float(obj.provident_fund_employer_percent or 0), ".1f") + "%")

    @display(description="Social Security")
    def social_security_display(self, obj):
        v = float(obj.social_security_fixed or 0)
        if v == 0:
            return format_html('<span class="sl-muted">—</span>')
        return format_html('<span class="sl-stat-amt">PKR {}</span>', format(v, ",.0f"))

    @display(description="Status")
    def is_active_display(self, obj):
        return "Active" if obj.is_active else "Inactive"

    def has_module_permission(self, request): return not _is_manager(request) and super().has_module_permission(request)
    def has_view_permission(self, request, obj=None): return not _is_manager(request) and super().has_view_permission(request, obj)
    def has_add_permission(self, request): return not _is_manager(request) and super().has_add_permission(request)
    def has_change_permission(self, request, obj=None): return not _is_manager(request) and super().has_change_permission(request, obj)
    def has_delete_permission(self, request, obj=None): return not _is_manager(request) and super().has_delete_permission(request, obj)


# ══════════════════════════════════════════════════════════════════════════════
# SALARY REVISION INLINE + STANDALONE ADMIN
# ══════════════════════════════════════════════════════════════════════════════

class SalaryRevisionInline(admin.TabularInline):
    model = SalaryRevision
    extra = 0
    fields = ("effective_from", "effective_to", "basic_salary",
              "house_rent_allowance", "medical_allowance", "payment_mode", "reason")
    can_delete = True
    verbose_name = "Salary Revision"
    verbose_name_plural = "Salary Revision History"


@admin.register(SalaryRevision)
class SalaryRevisionAdmin(admin.ModelAdmin):
    change_form_template = "admin/salary/salaryrevision/change_form.html"
    list_display = ("__str__", "effective_from", "effective_to", "payment_mode", "created_at")
    list_filter = ("payment_mode",)
    search_fields = ("salary_setup__employee__full_name", "salary_setup__employee__employee_code")
    autocomplete_fields = ("salary_setup",)
    readonly_fields = ("created_at", "created_by")

    def save_model(self, request, obj, form, change):
        if not obj.pk:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


# ══════════════════════════════════════════════════════════════════════════════
# SALARY SETUP
# ══════════════════════════════════════════════════════════════════════════════

@admin.register(SalarySetup)
class SalarySetupAdmin(admin.ModelAdmin):
    list_display = (
        "employee_display", "gross_display", "components_bar",
        "deductions_display", "net_display",
        "payment_mode_display", "status_display",
    )
    list_filter = ("payment_mode", "is_active")
    search_fields = ("employee__full_name", "employee__employee_code", "employee__official_email")
    autocomplete_fields = ("employee",)
    readonly_fields = ("salary_summary_display", "created_at", "updated_at")
    inlines = [SalaryRevisionInline]

    fieldsets = (
        ("Live Salary Summary", {"fields": ("salary_summary_display",)}),
        ("Employee & Compensation", {
            "fields": (
                "employee",
                ("gross_salary_input", "currency"),
                ("basic_salary", "house_rent_allowance"),
                ("utility_allowance", "medical_allowance"),
                ("conveyance_allowance", "other_allowance"),
                ("total_working_days", "ntn_no"),
                "is_active",
            ),
            "description": "Enter Gross Salary — Basic (60%), HRA (20%), Utility (10%), Medical (10%) "
                           "auto-filled. Or enter each component manually.",
        }),
        ("Deductions", {
            "fields": (
                ("absent_days", "unpaid_days"),
                ("loan_installment", "advance_salary_repayment"),
                ("eobi_contribution", "pessi_contribution"),
                ("gratuity_deduction", "provident_fund_deduction"),
                "misc_deduction",
            ),
            "description": "Monthly deduction amounts applied to this employee's payslip.",
        }),
        ("Payment Details", {
            "fields": ("payment_mode", ("bank_name", "account_title"), "account_number"),
            "description": "Bank name, account title, and account number required for Bank payments.",
        }),
        ("Loans & Advances", {"fields": (
            ("general_total_loan", "general_paid_loan", "general_balance_loan"),
            ("pf_total_loan", "pf_paid_loan", "pf_balance_loan"),
        )}),
        ("Provident Fund Ledger", {"fields": (
            ("pf_starting_balance_own", "pf_starting_balance_company"),
            "pf_record_date",
            ("pf_permanent_loan_own", "pf_permanent_loan_company"),
            ("pf_refundable_loan_own", "pf_refundable_loan_company"),
        )}),
        ("Notes & Audit", {"fields": ("notes", ("created_at", "updated_at"))}),
    )

    change_list_template = "admin/salary/salarysetup/change_list.html"

    # ── Changelist KPI injection ──────────────────────────────────────────────

    def changelist_view(self, request, extra_context=None):
        import json
        qs = SalarySetup.objects.filter(is_active=True).select_related("employee")
        total_employees = qs.count()
        total_gross = total_tax = total_net = total_ded = Decimal("0")
        total_basic = total_hra = total_util = total_med = Decimal("0")

        # Per-employee data for bar chart
        chart_labels = []
        chart_gross  = []
        chart_net    = []
        chart_tax    = []

        for setup in qs:
            try:
                r = calculate_salary_setup_breakdown(setup)
                total_gross += r["gross_salary"]
                total_tax   += r["monthly_income_tax"]
                total_net   += r["net_salary"]
                total_ded   += r["total_deductions"]
                total_basic += r["basic_salary"]
                total_hra   += r["house_rent_allowance"]
                total_util  += r["utility_allowance"]
                total_med   += r["medical_allowance"]
                name = (setup.employee.full_name or setup.employee.employee_code or "?").split()[0]
                chart_labels.append(name)
                chart_gross.append(float(r["gross_salary"]))
                chart_net.append(float(r["net_salary"]))
                chart_tax.append(float(r["monthly_income_tax"]))
            except Exception:
                pass

        avg_gross = (total_gross / total_employees) if total_employees else Decimal("0")

        # Donut: component breakdown of total payroll
        gf = float(total_gross) or 1
        donut_data = [
            round(float(total_basic) / gf * 100, 1),
            round(float(total_hra)   / gf * 100, 1),
            round(float(total_util)  / gf * 100, 1),
            round(float(total_med)   / gf * 100, 1),
            round(float(total_ded)   / gf * 100, 1),
        ]

        extra_context = extra_context or {}
        extra_context.update({
            "kpi_total_employees": total_employees,
            "kpi_total_gross":     float(total_gross),
            "kpi_total_tax":       float(total_tax),
            "kpi_total_net":       float(total_net),
            "kpi_total_ded":       float(total_ded),
            "kpi_avg_gross":       float(avg_gross),
            # Chart JSON for template
            "chart_labels_json":   json.dumps(chart_labels),
            "chart_gross_json":    json.dumps(chart_gross),
            "chart_net_json":      json.dumps(chart_net),
            "chart_tax_json":      json.dumps(chart_tax),
            "donut_data_json":     json.dumps(donut_data),
        })
        return super().changelist_view(request, extra_context=extra_context)

    # ── List columns ──────────────────────────────────────────────────────────

    @display(description="Employee")
    def employee_display(self, obj):
        emp = obj.employee
        initials = (emp.full_name or "?")[0].upper()
        if getattr(emp, "profile_photo", None) and emp.profile_photo:
            avatar = format_html('<img src="{}" class="sl-emp-avatar" alt="">', emp.profile_photo.url)
        else:
            avatar = format_html('<div class="sl-emp-avatar sl-emp-avatar-ph">{}</div>', initials)
        return format_html(
            '<div class="sl-emp-cell">{}<div>'
            '<div class="sl-emp-name">{}</div>'
            '<div class="sl-emp-meta">{} · {}</div>'
            '</div></div>',
            avatar, emp.full_name or "—",
            emp.employee_code or "—", emp.department or "—",
        )

    @display(description="Gross Salary")
    def gross_display(self, obj):
        try:
            r = calculate_salary_setup_breakdown(obj)
            return format_html('<span class="sl-gross-amt">PKR {}</span>', format(float(r["gross_salary"]), ",.0f"))
        except Exception:
            return format_html('<span class="sl-muted">—</span>')

    @display(description="Components")
    def components_bar(self, obj):
        try:
            r = calculate_salary_setup_breakdown(obj)
            gf = float(r["gross_salary"]) or 1
            bp = round(float(r["basic_salary"])         / gf * 100)
            hp = round(float(r["house_rent_allowance"]) / gf * 100)
            up = round(float(r["utility_allowance"])    / gf * 100)
            mp = round(float(r["medical_allowance"])    / gf * 100)
            return format_html(
                '<div class="sl-comp-wrap">'
                '<div class="sl-comp-bar">'
                '<div class="sl-seg sl-seg-basic" style="width:{0}%" title="Basic {0}%"></div>'
                '<div class="sl-seg sl-seg-hra"   style="width:{1}%" title="HRA {1}%"></div>'
                '<div class="sl-seg sl-seg-util"  style="width:{2}%" title="Utility {2}%"></div>'
                '<div class="sl-seg sl-seg-med"   style="width:{3}%" title="Medical {3}%"></div>'
                '</div><span class="sl-comp-lbl">{0}% basic</span></div>',
                bp, hp, up, mp)
        except Exception:
            return format_html('<span class="sl-muted">—</span>')

    @display(description="Deductions")
    def deductions_display(self, obj):
        try:
            r = calculate_salary_setup_breakdown(obj)
            gf  = float(r["gross_salary"]) or 1
            ded = float(r["total_deductions"])
            pct = min(round(ded / gf * 100), 100)
            return format_html(
                '<div class="sl-ded-cell">'
                '<span class="sl-ded-amt">PKR {}</span>'
                '<div class="sl-ded-track"><div class="sl-ded-fill" style="width:{pct}%"></div></div>'
                '<span class="sl-ded-pct">{pct}%</span>'
                '</div>',
                ded, pct=pct)
        except Exception:
            return format_html('<span class="sl-muted">—</span>')

    @display(description="Net Salary")
    def net_display(self, obj):
        try:
            r = calculate_salary_setup_breakdown(obj)
            return format_html('<span class="sl-net-amt">PKR {}</span>', format(float(r["net_salary"]), ",.0f"))
        except Exception:
            return format_html('<span class="sl-muted">—</span>')

    @display(description="Payment")
    def payment_mode_display(self, obj):
        return obj.payment_mode

    @display(description="Status")
    def status_display(self, obj):
        return "Active" if obj.is_active else "Inactive"

    # ── Live salary summary card (change form readonly field) ─────────────────

    @display(description="Salary Breakdown")
    def salary_summary_display(self, obj):
        if not obj or not obj.pk:
            return format_html(
                '<div class="sl-sum-empty">'
                '<svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="#D1D5DB" stroke-width="1.5">'
                '<rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/>'
                '</svg><p>Save the record first — the salary breakdown will appear here.</p></div>')
        try:
            r       = calculate_salary_setup_breakdown(obj)
            gross   = float(r["gross_salary"])
            net     = float(r["net_salary"])
            tax     = float(r["monthly_income_tax"])
            tot_ded = float(r["total_deductions"])
            basic   = float(r["basic_salary"])
            hra     = float(r["house_rent_allowance"])
            util    = float(r["utility_allowance"])
            med     = float(r["medical_allowance"])
            att_ded = float(r["attendance_deduction"])
            taxable = float(r["monthly_taxable_income"])

            gf      = gross or 1
            net_pct = min(round(net / gf * 100), 100)
            gross_fmt = format(gross, ",.0f")
            net_fmt = format(net, ",.0f")
            tax_fmt = format(tax, ",.0f")
            tot_ded_fmt = format(tot_ded, ",.0f")
            basic_fmt = format(basic, ",.0f")
            basic_pct_fmt = format(round(basic / gf * 100), ".0f")
            hra_fmt = format(hra, ",.0f")
            hra_pct_fmt = format(round(hra / gf * 100), ".0f")
            util_fmt = format(util, ",.0f")
            med_fmt = format(med, ",.0f")
            att_ded_fmt = format(att_ded, ",.0f")
            loan_total  = float(obj.loan_installment or 0) + float(obj.advance_salary_repayment or 0)
            stat_total  = float(obj.eobi_contribution or 0) + float(obj.pessi_contribution or 0)
            other_total = float(obj.gratuity_deduction or 0) + float(obj.provident_fund_deduction or 0) + float(obj.misc_deduction or 0)
            loan_total_fmt = format(loan_total, ",.0f")
            stat_total_fmt = format(stat_total, ",.0f")
            other_total_fmt = format(other_total, ",.0f")
            annual_gross_fmt = format(gross * 12, ",.0f")
            annual_tax_fmt = format(tax * 12, ",.0f")
            annual_net_fmt = format(net * 12, ",.0f")
            taxable_fmt = format(taxable, ",.0f")

            kpis = format_html(
                '<div class="sl-sum-kpis">'
                '<div class="sl-sum-kpi sl-kpi-gross"><span class="sl-kpi-v">PKR {}</span><span class="sl-kpi-l">Gross Salary</span></div>'
                '<div class="sl-sum-kpi sl-kpi-net"><span class="sl-kpi-v">PKR {}</span><span class="sl-kpi-l">Net Pay</span></div>'
                '<div class="sl-sum-kpi sl-kpi-tax"><span class="sl-kpi-v">PKR {}</span><span class="sl-kpi-l">Income Tax / mo</span></div>'
                '<div class="sl-sum-kpi sl-kpi-ded"><span class="sl-kpi-v">PKR {}</span><span class="sl-kpi-l">Total Deductions</span></div>'
                '</div>',
                gross_fmt, net_fmt, tax_fmt, tot_ded_fmt)

            net_bar = format_html(
                '<div class="sl-net-bar-row">'
                '<span class="sl-nb-label">Net pay is {pct}% of gross</span>'
                '<div class="sl-nb-track"><div class="sl-nb-fill" style="width:{pct}%"></div></div>'
                '<span class="sl-nb-pct">{pct}%</span>'
                '</div>', pct=net_pct)

            earnings = format_html(
                '<div class="sl-sum-col">'
                '<div class="sl-col-head sl-head-earn">'
                '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg>Earnings</div>'
                '<div class="sl-sum-row"><span class="sl-r-lbl">Basic Salary <em>60%</em></span><span class="sl-r-val">PKR {}</span></div>'
                '<div class="sl-comp-mini-bar"><div class="sl-cmb-fill sl-cmb-basic" style="width:{}%"></div></div>'
                '<div class="sl-sum-row"><span class="sl-r-lbl">House Rent <em>20%</em></span><span class="sl-r-val">PKR {}</span></div>'
                '<div class="sl-comp-mini-bar"><div class="sl-cmb-fill sl-cmb-hra" style="width:{}%"></div></div>'
                '<div class="sl-sum-row"><span class="sl-r-lbl">Utility <em>10%</em></span><span class="sl-r-val">PKR {}</span></div>'
                '<div class="sl-sum-row"><span class="sl-r-lbl">Medical <em>10%</em></span><span class="sl-r-val">PKR {}</span></div>'
                '<div class="sl-sum-total"><span>Gross Pay</span><span class="sl-t-val">PKR {}</span></div>'
                '</div>',
                basic_fmt, basic_pct_fmt, hra_fmt, hra_pct_fmt, util_fmt, med_fmt, gross_fmt)

            deductions = format_html(
                '<div class="sl-sum-col">'
                '<div class="sl-col-head sl-head-ded">'
                '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="8" y1="12" x2="16" y2="12"/></svg>Deductions</div>'
                '<div class="sl-sum-row"><span class="sl-r-lbl">Income Tax</span><span class="sl-r-val sl-neg">PKR {}</span></div>'
                '<div class="sl-sum-row"><span class="sl-r-lbl">Attendance Deduction</span><span class="sl-r-val sl-neg">PKR {}</span></div>'
                '<div class="sl-sum-row"><span class="sl-r-lbl">EOBI + PESSI</span><span class="sl-r-val sl-neg">PKR {}</span></div>'
                '<div class="sl-sum-row"><span class="sl-r-lbl">Loan + Advance Recovery</span><span class="sl-r-val sl-neg">PKR {}</span></div>'
                '<div class="sl-sum-row"><span class="sl-r-lbl">PF + Gratuity + Misc</span><span class="sl-r-val sl-neg">PKR {}</span></div>'
                '<div class="sl-sum-total sl-sum-net"><span>Net Pay</span><span class="sl-t-val sl-t-net">PKR {}</span></div>'
                '</div>',
                tax_fmt, att_ded_fmt, stat_total_fmt, loan_total_fmt, other_total_fmt, net_fmt)

            footer = format_html(
                '<div class="sl-sum-footer">'
                '<div class="sl-sf-item"><span class="sl-sf-lbl">Annual Gross</span><span class="sl-sf-val">PKR {}</span></div>'
                '<div class="sl-sf-sep"></div>'
                '<div class="sl-sf-item"><span class="sl-sf-lbl">Annual Tax</span><span class="sl-sf-val">PKR {}</span></div>'
                '<div class="sl-sf-sep"></div>'
                '<div class="sl-sf-item"><span class="sl-sf-lbl">Annual Net</span><span class="sl-sf-val">PKR {}</span></div>'
                '<div class="sl-sf-sep"></div>'
                '<div class="sl-sf-item"><span class="sl-sf-lbl">Monthly Taxable</span><span class="sl-sf-val">PKR {}</span></div>'
                '</div>',
                annual_gross_fmt, annual_tax_fmt, annual_net_fmt, taxable_fmt)

            return format_html(
                '<div class="sl-summary-card">{kpis}{net_bar}'
                '<div class="sl-sum-body">{earn}{ded}</div>{footer}</div>',
                kpis=kpis, net_bar=net_bar, earn=earnings, ded=deductions, footer=footer)

        except Exception as e:
            return format_html('<div class="sl-sum-err">Could not compute summary: {}</div>', str(e))

    class Media:
        js  = ("salary/js/salary_setup_autofill.js",)
        css = {"all": ("salary/css/salary_admin.css", "salary/css/salary_preview_modal.css",)}

    def has_module_permission(self, request): return request.user.is_authenticated and not _is_manager(request)
    def has_view_permission(self, request, obj=None): return request.user.is_authenticated and not _is_manager(request)
    def has_add_permission(self, request): return request.user.is_authenticated and not _is_manager(request)
    def has_change_permission(self, request, obj=None): return request.user.is_authenticated and not _is_manager(request)
    def has_delete_permission(self, request, obj=None): return request.user.is_authenticated and not _is_manager(request)

@admin.register(Payslip)
class PayslipAdmin(admin.ModelAdmin):
    change_list_template = "admin/salary/payslip/change_list.html"
    change_form_template = "admin/salary/payslip/change_form.html"
    list_display = (
        "payroll_run", "employee_display", "gross_salary_display",
        "net_salary_display", "status_badge", "is_paid_display",
        "updated_at_display",
    )
    list_display_links = ("employee_display",)
    list_filter = ("payroll_run__year", "payroll_run__month", "status", "is_paid")
    list_filter_submit = True
    search_fields = (
        "employee__full_name", "employee__employee_code",
        "payroll_run__year", "payroll_run__month",
    )
    autocomplete_fields = ("employee", "payroll_run")
    readonly_fields = (
        "paid_at", "paid_by",
        "salary_revision", "gross_salary", "taxable_salary", "income_tax",
        "total_deductions", "net_salary", "employer_contribution",
        "total_employer_cost", "approved_by", "approved_at",
        "created_at", "updated_at",
    )
    actions = ("finalize_payslips", "reopen_payslips", "mark_as_paid", "mark_as_unpaid")

    # ── Custom URLs ───────────────────────────────────────────────────────────

    def get_urls(self):
        urls = super().get_urls()
        return [
            path(
                "employee/<int:employee_pk>/",
                self.admin_site.admin_view(self.employee_payslip_view),
                name="salary_employee_payslip_history",
            ),
        ] + urls

    # ── Per-employee payslip history view ─────────────────────────────────────

    def employee_payslip_view(self, request, employee_pk):
        from django.shortcuts import get_object_or_404

        employee = get_object_or_404(EmployeeProfile, pk=employee_pk)
        today = date.today()

        # All payslips for this employee (all time)
        all_payslips = (
            Payslip.objects.filter(employee=employee)
            .select_related("payroll_run", "salary_revision")
            .order_by("-payroll_run__year", "-payroll_run__month")
        )

        # Years that have data
        years = sorted(
            set(ps.payroll_run.year for ps in all_payslips),
            reverse=True,
        )
        if not years:
            years = [today.year]

        # Selected year
        try:
            selected_year = int(request.GET.get("year", years[0]))
        except (ValueError, TypeError):
            selected_year = years[0]

        year_payslips = [ps for ps in all_payslips if ps.payroll_run.year == selected_year]

        # YTD aggregates for selected year
        ytd_qs = all_payslips.filter(payroll_run__year=selected_year)
        ytd = ytd_qs.aggregate(
            gross=Sum("gross_salary"),
            net=Sum("net_salary"),
            tax=Sum("income_tax"),
            deductions=Sum("total_deductions"),
        )
        ytd_gross = float(ytd["gross"] or 0)
        ytd_net   = float(ytd["net"]   or 0)
        ytd_tax   = float(ytd["tax"]   or 0)
        ytd_ded   = float(ytd["deductions"] or 0)
        months_processed = len(year_payslips)
        paid_months      = sum(1 for ps in year_payslips if ps.is_paid)

        # Month rows
        month_rows = []
        for ps in year_payslips:
            run = ps.payroll_run
            gross = float(ps.gross_salary or 0)
            net   = float(ps.net_salary   or 0)
            gf    = gross or 1
            month_rows.append({
                "payslip":       ps,
                "run":           run,
                "month_label":   date(run.year, run.month, 1).strftime("%B %Y"),
                "gross":         gross,
                "net":           net,
                "tax":           float(ps.income_tax      or 0),
                "deductions":    float(ps.total_deductions or 0),
                "overtime":      float(ps.overtime_amount),
                "bonus":         float(ps.bonus           or 0),
                "unpaid_days":   float(ps.unpaid_leave_days or 0),
                "net_pct":       min(round(net / gf * 100), 100),
            })

        context = {
            **self.admin_site.each_context(request),
            "title": f"{employee.full_name} — Payslip History",
            "opts": self.model._meta,
            "app_label": self.model._meta.app_label,
            "employee": employee,
            "years": years,
            "selected_year": selected_year,
            "month_rows": month_rows,
            "ytd_gross": ytd_gross,
            "ytd_net":   ytd_net,
            "ytd_tax":   ytd_tax,
            "ytd_ded":   ytd_ded,
            "months_processed": months_processed,
            "paid_months":      paid_months,
        }
        return render(request, "admin/salary/employee_payslip_history.html", context)

    fieldsets = (
        ("Payroll Details", {"fields": ("payroll_run", "employee", "status", "is_paid")} ),
        ("Salary Summary", {"fields": (
            "gross_salary", "taxable_salary", "income_tax", "total_deductions",
            "net_salary",
        )}),
        ("Payment Info", {"fields": ("paid_at", "paid_by")} ),
        ("Review", {"fields": ("approved_by", "approved_at")} ),
        ("Audit", {"fields": ("created_at", "updated_at")} ),
    )

    @display(description="Employee")
    def employee_display(self, obj):
        url = reverse("admin:salary_employee_payslip_history", args=[obj.employee.pk])
        return format_html(
            '<a href="{}" class="sl-emp-history-link">'
            '<div><strong>{}</strong>'
            '<div class="sl-emp-meta">{}</div></div>'
            '</a>',
            url,
            obj.employee.full_name or "—",
            obj.employee.employee_code or "—",
        )

    @display(description="Gross Salary")
    def gross_salary_display(self, obj):
        return format_html(
            '<span class="sl-gross-amt">PKR {}</span>',
            format(float(obj.gross_salary or 0), ",.0f"),
        )

    @display(description="Income Tax")
    def income_tax_display(self, obj):
        return format_html(
            '<span class="sl-tax-amt">PKR {}</span>',
            format(float(obj.income_tax or 0), ",.0f"),
        )

    @display(description="Deductions")
    def total_deductions_display(self, obj):
        return format_html(
            '<span class="sl-ded-amt">PKR {}</span>',
            format(float(obj.total_deductions or 0), ",.0f"),
        )

    @display(description="Net Salary")
    def net_salary_display(self, obj):
        return format_html(
            '<span class="sl-net-amt">PKR {}</span>',
            format(float(obj.net_salary or 0), ",.0f"),
        )

    @display(description="Status")
    def status_badge(self, obj):
        return obj.status

    @display(description="Paid")
    def is_paid_display(self, obj):
        return "Paid" if obj.is_paid else "Unpaid"

    @action(description="Finalize selected payslips")
    def finalize_payslips(self, request, queryset):
        updated = queryset.filter(status=Payslip.StatusChoices.DRAFT).update(status=Payslip.StatusChoices.FINALIZED)
        self.message_user(request, f"Marked {updated} payslip(s) as Finalized.", level=messages.SUCCESS)

    @action(description="Reopen selected payslips")
    def reopen_payslips(self, request, queryset):
        updated = queryset.filter(status=Payslip.StatusChoices.FINALIZED).update(status=Payslip.StatusChoices.DRAFT)
        self.message_user(request, f"Marked {updated} payslip(s) as Draft.", level=messages.SUCCESS)

    @action(description="Mark selected payslips as paid")
    def mark_as_paid(self, request, queryset):
        updated = queryset.update(is_paid=True, paid_at=timezone.now(), paid_by=request.user)
        self.message_user(request, f"Marked {updated} payslip(s) as Paid.", level=messages.SUCCESS)

    @action(description="Mark selected payslips as unpaid")
    def mark_as_unpaid(self, request, queryset):
        updated = queryset.update(is_paid=False, paid_at=None, paid_by=None)
        self.message_user(request, f"Marked {updated} payslip(s) as Unpaid.", level=messages.SUCCESS)

    @display(description="Last Updated")
    def updated_at_display(self, obj):
        return obj.updated_at.strftime("%d %b %Y %H:%M") if obj.updated_at else "—"

    def has_module_permission(self, request): return request.user.is_authenticated and not _is_manager(request)
    def has_view_permission(self, request, obj=None): return request.user.is_authenticated and not _is_manager(request)
    def has_add_permission(self, request): return request.user.is_authenticated and not _is_manager(request)
    def has_change_permission(self, request, obj=None): return request.user.is_authenticated and not _is_manager(request)
    def has_delete_permission(self, request, obj=None): return request.user.is_authenticated and not _is_manager(request)
# ══════════════════════════════════════════════════════════════════════════════
# PAYROLL RUN
# ══════════════════════════════════════════════════════════════════════════════

@admin.register(PayrollRun)
class PayrollRunAdmin(admin.ModelAdmin):
    change_list_template = "admin/salary/payrollrun/change_list.html"
    change_form_template = "admin/salary/payrollrun/change_form.html"
    list_display = (
        "period_display", "status_badge",
        "payslip_count_display", "paid_count_display",
        "total_gross_display", "total_net_display",
        "total_tax_display", "created_at_display",
    )
    list_filter = ("status", "year", "month")
    list_filter_submit = True
    search_fields = ("notes",)
    readonly_fields = ("payslip_grid_display", "created_at", "updated_at")
    list_before_template = "admin/salary/payrollrun/kpi_cards.html"
    actions = ("generate_payslips_action", "finalize_runs_action")
    actions_row = ["generate_payslips_row", "finalize_run_row"]

    def get_urls(self):
        from django.urls import path
        urls = super().get_urls()
        custom = [
            path(
                "<int:object_id>/generate-payslips/",
                self.admin_site.admin_view(self.generate_payslips_row),
                name="salary_payrollrun_generate_payslips",
            ),
            path(
                "<int:object_id>/finalize/",
                self.admin_site.admin_view(self.finalize_run_row),
                name="salary_payrollrun_finalize",
            ),
        ]
        return custom + urls

    def change_view(self, request, object_id, form_url="", extra_context=None):
        extra_context = extra_context or {}
        extra_context["generate_url"] = reverse("admin:salary_payrollrun_generate_payslips", args=[object_id])
        extra_context["finalize_url"] = reverse("admin:salary_payrollrun_finalize", args=[object_id])
        try:
            run = PayrollRun.objects.get(pk=object_id)
            extra_context["run_is_locked"] = run.status == PayrollRun.StatusChoices.LOCKED
        except PayrollRun.DoesNotExist:
            pass
        return super().change_view(request, object_id, form_url, extra_context)

    fieldsets = (
        ("Payroll Run", {
            "fields": (("year", "month"), "status", "notes"),
            "description": "Create or edit a payroll run, then generate payslips and manage payment status." ,
        }),
        ("Summary", {"fields": ("payslip_grid_display",)}),
        ("Audit", {"fields": (("created_at", "updated_at"),)}),
    )

    # ── Changelist KPI injection ──────────────────────────────────────────────

    def changelist_view(self, request, extra_context=None):
        today = date.today()
        all_runs = PayrollRun.objects.all()
        total_runs = all_runs.count()

        # This month's run
        current_run = all_runs.filter(year=today.year, month=today.month).first()

        # Year-to-date stats
        ytd_gross = ytd_net = ytd_tax = Decimal("0")
        ytd_runs  = all_runs.filter(year=today.year)
        for run in ytd_runs:
            agg = run.payslips.aggregate(
                g=Sum("gross_salary"), n=Sum("net_salary"), t=Sum("income_tax"))
            ytd_gross += agg["g"] or Decimal("0")
            ytd_net   += agg["n"] or Decimal("0")
            ytd_tax   += agg["t"] or Decimal("0")

        # Monthly rows (last 6 months)
        monthly_rows = []
        yr, mo = today.year, today.month
        from datetime import date as _date
        for _ in range(6):
            run = all_runs.filter(year=yr, month=mo).first()
            if run:
                agg = run.payslips.aggregate(
                    g=Sum("gross_salary"), n=Sum("net_salary"),
                    t=Sum("income_tax"), cnt=Sum("id"))
                emp_count  = run.payslips.count()
                finalized  = run.payslips.filter(status=Payslip.StatusChoices.FINALIZED).count()
                monthly_rows.insert(0, {
                    "label":       _date(yr, mo, 1).strftime("%b %Y"),
                    "status":      run.status,
                    "run_pk":      run.pk,
                    "emp_count":   emp_count,
                    "finalized":   finalized,
                    "gross":       float(agg["g"] or 0),
                    "net":         float(agg["n"] or 0),
                    "tax":         float(agg["t"] or 0),
                    "is_current":  yr == today.year and mo == today.month,
                })
            else:
                monthly_rows.insert(0, {
                    "label":      _date(yr, mo, 1).strftime("%b %Y"),
                    "status":     None,
                    "run_pk":     None,
                    "emp_count":  0,
                    "finalized":  0,
                    "gross":      0,
                    "net":        0,
                    "tax":        0,
                    "is_current": yr == today.year and mo == today.month,
                })
            mo -= 1
            if mo == 0:
                mo = 12; yr -= 1

        extra_context = extra_context or {}
        extra_context.update({
            "pr_total_runs":    total_runs,
            "pr_current_run":   current_run,
            "pr_ytd_gross":     float(ytd_gross),
            "pr_ytd_net":       float(ytd_net),
            "pr_ytd_tax":       float(ytd_tax),
            "pr_monthly_rows":  monthly_rows,
            "pr_today_label":   today.strftime("%B %Y"),
        })
        return super().changelist_view(request, extra_context=extra_context)

    # ── List columns ──────────────────────────────────────────────────────────

    @display(description="Period")
    def period_display(self, obj):
        from datetime import date as _date
        label = _date(obj.year, obj.month, 1).strftime("%B %Y")
        return format_html(
            '<div class="sl-emp-cell">'
            '<div class="sl-pr-month-icon">{}</div>'
            '<div><div class="sl-emp-name">{}</div>'
            '<div class="sl-emp-meta">Payroll Run #{}</div></div>'
            '</div>',
            _date(obj.year, obj.month, 1).strftime("%b"), label, obj.pk or "—")

    @display(description="Status")
    def status_badge(self, obj):
        return obj.status

    @display(description="Payslips")
    def payslip_count_display(self, obj):
        total = obj.payslips.count()
        if total == 0:
            return format_html('<span class="sl-muted">0</span>')
        return format_html('<strong>{}</strong>', total)

    @display(description="Paid")
    def paid_count_display(self, obj):
        count = obj.payslips.filter(is_paid=True).count()
        if count == 0:
            return format_html('<span class="sl-muted">0</span>')
        return format_html('<strong>{}</strong>', count)

    @display(description="Gross Payroll")
    def total_gross_display(self, obj):
        agg = obj.payslips.aggregate(total=Sum("gross_salary"))
        v   = float(agg["total"] or 0)
        if v == 0:
            return format_html('<span class="sl-muted">—</span>')
        return format_html('<span class="sl-gross-amt">PKR {}</span>', format(v, ",.0f"))

    @display(description="Net Payroll")
    def total_net_display(self, obj):
        agg = obj.payslips.aggregate(total=Sum("net_salary"))
        v   = float(agg["total"] or 0)
        if v == 0:
            return format_html('<span class="sl-muted">—</span>')
        return format_html('<span class="sl-net-amt">PKR {}</span>', format(v, ",.0f"))

    @display(description="Total Tax")
    def total_tax_display(self, obj):
        agg = obj.payslips.aggregate(total=Sum("income_tax"))
        v   = float(agg["total"] or 0)
        if v == 0:
            return format_html('<span class="sl-muted">—</span>')
        return format_html('<span class="sl-tax-amt">PKR {}</span>', format(v, ",.0f"))

    @display(description="Created")
    def created_at_display(self, obj):
        if not obj.created_at:
            return "—"
        return format_html('<span class="sl-period">{}</span>', obj.created_at.strftime("%d %b %Y"))

    # ── Row actions ───────────────────────────────────────────────────────────

    @action(description="Generate Payslips")
    def generate_payslips_row(self, request, object_id):
        try:
            run = PayrollRun.objects.get(pk=object_id)
        except PayrollRun.DoesNotExist:
            self.message_user(request, "Payroll run not found.", level=messages.ERROR)
            return redirect(reverse("admin:salary_payrollrun_changelist"))
        if run.status == PayrollRun.StatusChoices.LOCKED:
            self.message_user(request, "Cannot regenerate payslips for a locked run.", level=messages.WARNING)
            return redirect(reverse("admin:salary_payrollrun_change", args=[object_id]))
        count = generate_payslips(run, created_by=request.user)
        self.message_user(request, f"Generated {count} payslip(s) for {run}.", level=messages.SUCCESS)
        return redirect(reverse("admin:salary_payrollrun_change", args=[object_id]))

    @action(description="Finalize All")
    def finalize_run_row(self, request, object_id):
        try:
            run = PayrollRun.objects.get(pk=object_id)
        except PayrollRun.DoesNotExist:
            self.message_user(request, "Payroll run not found.", level=messages.ERROR)
            return redirect(reverse("admin:salary_payrollrun_changelist"))
        if run.status == PayrollRun.StatusChoices.LOCKED:
            self.message_user(request, "Run is locked.", level=messages.WARNING)
            return redirect(reverse("admin:salary_payrollrun_change", args=[object_id]))
        updated = run.payslips.filter(status=Payslip.StatusChoices.DRAFT).update(
            status=Payslip.StatusChoices.FINALIZED)
        run.status = PayrollRun.StatusChoices.APPROVED
        run.save()
        self.message_user(request, f"Finalized {updated} payslip(s). Run marked Approved.", level=messages.SUCCESS)
        return redirect(reverse("admin:salary_payrollrun_change", args=[object_id]))

    @action(description="Generate Payslips for selected runs")
    def generate_payslips_action(self, request, queryset):
        total = 0
        for run in queryset:
            if run.status == PayrollRun.StatusChoices.LOCKED:
                continue
            total += generate_payslips(run, created_by=request.user)
        self.message_user(request, f"Generated {total} payslip(s) across selected payroll runs.", level=messages.SUCCESS)

    @action(description="Finalize selected runs")
    def finalize_runs_action(self, request, queryset):
        total = 0
        for run in queryset:
            if run.status == PayrollRun.StatusChoices.LOCKED:
                continue
            updated = run.payslips.filter(status=Payslip.StatusChoices.DRAFT).update(status=Payslip.StatusChoices.FINALIZED)
            run.status = PayrollRun.StatusChoices.APPROVED
            run.save()
            total += updated
        self.message_user(request, f"Finalized {total} payslip(s) across selected payroll runs.", level=messages.SUCCESS)

    # ── Payslip grid (change form readonly field) ─────────────────────────────

    @display(description="Employee Payslips")
    def payslip_grid_display(self, obj):
        if not obj or not obj.pk:
            return format_html(
                '<div class="sl-sum-empty">'
                '<svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="#D1D5DB" stroke-width="1.5">'
                '<rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/>'
                '</svg><p>Save this run first, then click <strong>Generate Payslips</strong> from the list.</p></div>')

        payslips = (obj.payslips
                    .select_related("employee")
                    .order_by("employee__full_name"))
        if not payslips.exists():
            return format_html(
                '<div class="sl-sum-empty">'
                '<svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="#D1D5DB" stroke-width="1.5">'
                '<path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/>'
                '</svg>'
                '<p>No payslips yet. Go back to the list and click <strong>Generate Payslips ↻</strong> '
                'next to this run.</p></div>')

        agg = payslips.aggregate(
            tg=Sum("gross_salary"), tn=Sum("net_salary"),
            tt=Sum("income_tax"), td=Sum("total_deductions"))
        total_gross = float(agg["tg"] or 0)
        total_net   = float(agg["tn"] or 0)
        total_tax   = float(agg["tt"] or 0)
        total_ded   = float(agg["td"] or 0)
        total_emp   = payslips.count()
        paid        = payslips.filter(is_paid=True).count()
        pending     = total_emp - paid

        total_gross_fmt = format(total_gross, ",.0f")
        total_net_fmt = format(total_net, ",.0f")
        total_tax_fmt = format(total_tax, ",.0f")

        # ── Summary header ────────────────────────────────────────────────────
        header = format_html(
            '<div class="sl-summary-header">'
            '<div class="sl-sum-kpis">'
            '<div class="sl-sum-kpi sl-kpi-gross"><span class="sl-kpi-v">PKR {}</span><span class="sl-kpi-l">Total Gross</span></div>'
            '<div class="sl-sum-kpi sl-kpi-net"><span class="sl-kpi-v">PKR {}</span><span class="sl-kpi-l">Total Net</span></div>'
            '<div class="sl-sum-kpi sl-kpi-tax"><span class="sl-kpi-v">PKR {}</span><span class="sl-kpi-l">Total Tax</span></div>'
            '</div>'
            '<div class="sl-summary-stats sl-stat-row">'
            '<div class="sl-stat-chip sl-stat-avg"><strong>{}</strong> Paid</div>'
            '<div class="sl-stat-chip sl-stat-ded"><strong>{}</strong> Pending</div>'
            '</div>'
            '<div class="sl-table-label"><span class="sl-tl-dot"></span> Employee Payslips</div>'
            '</div>',
            total_gross_fmt, total_net_fmt, total_tax_fmt, paid, pending)

        # ── Table header ──────────────────────────────────────────────────────
        rows_html = format_html(
            '<table class="sl-ps-table">'
            '<thead><tr>'
            '<th>Employee</th>'
            '<th class="num">Gross</th>'
            '<th class="num">Tax</th>'
            '<th class="num">Deductions</th>'
            '<th class="num">Net Pay</th>'
            '<th class="num">Status</th>'
            '</tr></thead><tbody>')

        # ── Employee rows ─────────────────────────────────────────────────────
        row_parts = []
        for ps in payslips:
            emp       = ps.employee
            initials  = (emp.full_name or "?")[0].upper()
            is_paid   = ps.is_paid

            if getattr(emp, "profile_photo", None) and emp.profile_photo:
                avatar = format_html('<img src="{}" class="sl-emp-avatar" alt="">', emp.profile_photo.url)
            else:
                avatar = format_html('<div class="sl-emp-avatar sl-emp-avatar-ph">{}</div>', initials)

            gross  = float(ps.gross_salary   or 0)
            tax    = float(ps.income_tax     or 0)
            ded    = float(ps.total_deductions or 0)
            net    = float(ps.net_salary     or 0)
            gf     = gross or 1
            net_pct = min(round(net / gf * 100), 100)

            gross_fmt = format(gross, ",.0f")
            tax_fmt = format(tax, ",.0f")
            ded_fmt = format(ded, ",.0f")
            net_fmt = format(net, ",.0f")

            status_html = format_html(
                '<span class="sl-ps-status {}">{}</span>',
                "sl-ps-paid" if is_paid else "sl-ps-draft",
                "✓ Paid" if is_paid else "⏳ Pending")

            row_parts.append(format_html(
                '<tr class="sl-ps-row {}">'
                '<td><div class="sl-emp-cell">{}<div>'
                '<div class="sl-emp-name">{}</div>'
                '<div class="sl-emp-meta">{} · {}</div>'
                '</div></div></td>'
                '<td class="num"><span class="sl-gross-amt">PKR {}</span></td>'
                '<td class="num"><span class="sl-tax-amt">PKR {}</span></td>'
                '<td class="num">'
                '<div class="sl-ps-ded-wrap">'
                '<span class="sl-ded-amt">PKR {}</span>'
                '<div class="sl-ded-track"><div class="sl-ded-fill" style="width:{pct}%"></div></div>'
                '</div>'
                '</td>'
                '<td class="num"><span class="sl-net-amt">PKR {}</span></td>'
                '<td class="num">{}</td>'
                '</tr>',
                "sl-row-paid" if is_paid else "sl-row-draft",
                avatar,
                emp.full_name or "—",
                emp.employee_code or "—",
                emp.department or "—",
                gross_fmt, tax_fmt, ded_fmt,
                net_fmt, status_html,
                pct=min(round(ded / gf * 100), 100)))

        all_rows = format_html("{}" * len(row_parts), *row_parts)

        return format_html(
            '<div class="sl-ps-grid-wrap">'
            '<div class="sl-summary-card">'
            '{header}'
            '{rows_open}'
            '{rows}'
            '</tbody></table>'
            '</div>'
            '</div>',
            header=header,
            rows_open=rows_html,
            rows=all_rows)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if not change:
            count = generate_payslips(obj, created_by=request.user)
            if count:
                self.message_user(request, f"Auto-generated {count} payslip(s) for {obj}.", level=messages.SUCCESS)

    class Media:
        css = {"all": ("salary/css/salary_admin.css",)}

    def has_module_permission(self, request): return request.user.is_authenticated and not _is_manager(request)
    def has_view_permission(self, request, obj=None): return request.user.is_authenticated and not _is_manager(request)
    def has_add_permission(self, request): return request.user.is_authenticated and not _is_manager(request)
    def has_change_permission(self, request, obj=None): return request.user.is_authenticated and not _is_manager(request)
    def has_delete_permission(self, request, obj=None): return request.user.is_authenticated and not _is_manager(request)
