from django import template
from django.db.models import Sum
from django.utils import timezone

register = template.Library()


@register.simple_tag
def salary_dashboard_stats():
    from salary.models import (
        PayrollRun, Payslip, SalarySetup,
        StatutoryDeductionPolicy, TaxYear,
    )
    today = timezone.localdate()

    payroll_total = PayrollRun.objects.count()
    payroll_draft = PayrollRun.objects.filter(status=PayrollRun.StatusChoices.DRAFT).count()
    payroll_locked = PayrollRun.objects.filter(status=PayrollRun.StatusChoices.LOCKED).count()
    latest_run = PayrollRun.objects.first()

    payslip_total = Payslip.objects.count()
    payslip_this_month = Payslip.objects.filter(
        payroll_run__year=today.year, payroll_run__month=today.month
    ).count()
    payslip_paid = Payslip.objects.filter(is_paid=True).count()

    setup_total = SalarySetup.objects.count()
    setup_active = SalarySetup.objects.filter(is_active=True).count()
    total_gross = SalarySetup.objects.filter(is_active=True).aggregate(
        t=Sum("gross_salary_input")
    )["t"] or 0

    statutory_total = StatutoryDeductionPolicy.objects.count()
    statutory_active = StatutoryDeductionPolicy.objects.filter(is_active=True).count()

    tax_total = TaxYear.objects.count()
    active_tax = TaxYear.objects.filter(is_active=True).first()

    return {
        "payroll": {
            "total": payroll_total,
            "draft": payroll_draft,
            "locked": payroll_locked,
            "latest": str(latest_run) if latest_run else "—",
            "latest_status": latest_run.status if latest_run else "—",
        },
        "payslip": {
            "total": payslip_total,
            "this_month": payslip_this_month,
            "paid": payslip_paid,
        },
        "setup": {
            "total": setup_total,
            "active": setup_active,
            "total_gross": int(total_gross),
        },
        "statutory": {
            "total": statutory_total,
            "active": statutory_active,
        },
        "tax": {
            "total": tax_total,
            "active_year": active_tax.fiscal_year if active_tax else "—",
            "active_from": active_tax.effective_from.strftime("%d %b %Y") if active_tax else "—",
        },
    }
