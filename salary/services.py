from calendar import monthrange
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from django.db import models
from django.db.models import Sum
from django.utils import timezone

from .models import (
    PayrollRun,
    Payslip,
    SalaryRevision,
    SalarySetup,
    SalaryTaxSlab,
    StatutoryDeductionPolicy,
)

TWOPLACES = Decimal("0.01")
DAYS_IN_MONTH_STANDARD = Decimal("30")


def q(value: Decimal) -> Decimal:
    return (value or Decimal("0")).quantize(TWOPLACES, rounding=ROUND_HALF_UP)


def get_applicable_tax_slab(annual_taxable_income: Decimal, on_date: date):
    return (
        SalaryTaxSlab.objects.filter(
            tax_year__is_active=True,
            tax_year__effective_from__lte=on_date,
        )
        .filter(
            models.Q(tax_year__effective_to__isnull=True) | models.Q(tax_year__effective_to__gte=on_date)
        )
        .filter(annual_min_income__lte=annual_taxable_income)
        .filter(models.Q(annual_max_income__isnull=True) | models.Q(annual_max_income__gte=annual_taxable_income))
        .order_by("-tax_year__effective_from", "sort_order", "annual_min_income")
        .first()
    )


def calculate_monthly_tax(gross_salary: Decimal, on_date: date | None = None) -> Decimal:
    if gross_salary is None:
        return Decimal("0")
    monthly_taxable = q(gross_salary * Decimal("0.90"))
    annual_taxable = monthly_taxable * Decimal("12")
    annual_tax = calculate_annual_tax_from_slab(annual_taxable)
    return q(annual_tax / Decimal("12"))


def calculate_annual_tax_from_slab(annual_taxable_income: Decimal) -> Decimal:
    ati = annual_taxable_income or Decimal("0")
    slab = get_applicable_tax_slab(annual_taxable_income=ati, on_date=timezone.localdate())
    if not slab:
        return Decimal("0")
    excess = ati - (slab.taxable_excess_over or Decimal("0"))
    if excess < 0:
        excess = Decimal("0")
    return q((slab.base_tax or Decimal("0")) + (excess * (slab.rate_percent or Decimal("0")) / Decimal("100")))


def calculate_salary_setup_breakdown(salary_setup: SalarySetup) -> dict[str, Decimal]:
    gross = q(salary_setup.gross_salary_input or salary_setup.gross_salary)
    basic = q(gross * Decimal("0.60"))
    house_rent = q(gross * Decimal("0.20"))
    utility = q(gross * Decimal("0.10"))
    medical = q(gross - basic - house_rent - utility)  # remainder ensures exact sum
    monthly_taxable = q(gross * Decimal("0.90"))
    annual_taxable = q(monthly_taxable * Decimal("12"))
    annual_tax = calculate_annual_tax_from_slab(annual_taxable)
    monthly_income_tax = q(annual_tax / Decimal("12"))

    working_days = Decimal(str(salary_setup.total_working_days or 0))
    unpaid_days = salary_setup.unpaid_days or Decimal("0")
    attendance_deduction = Decimal("0")
    if working_days > 0 and unpaid_days > 0:
        attendance_deduction = q((gross / working_days) * unpaid_days)

    total_deductions = q(
        monthly_income_tax
        + attendance_deduction
        + (salary_setup.loan_installment or Decimal("0"))
        + (salary_setup.advance_salary_repayment or Decimal("0"))
        + (salary_setup.eobi_contribution or Decimal("0"))
        + (salary_setup.pessi_contribution or Decimal("0"))
        + (salary_setup.gratuity_deduction or Decimal("0"))
        + (salary_setup.provident_fund_deduction or Decimal("0"))
        + (salary_setup.misc_deduction or Decimal("0"))
    )
    net_salary = q(gross - total_deductions)
    return {
        "gross_salary": gross,
        "basic_salary": basic,
        "house_rent_allowance": house_rent,
        "utility_allowance": utility,
        "medical_allowance": medical,
        "monthly_taxable_income": monthly_taxable,
        "annual_taxable_income": annual_taxable,
        "annual_tax": annual_tax,
        "monthly_income_tax": monthly_income_tax,
        "attendance_deduction": attendance_deduction,
        "total_deductions": total_deductions,
        "net_salary": net_salary,
    }


def get_statutory_policy(on_date: date):
    return (
        StatutoryDeductionPolicy.objects.filter(is_active=True, effective_from__lte=on_date)
        .filter(models.Q(effective_to__isnull=True) | models.Q(effective_to__gte=on_date))
        .order_by("-effective_from")
        .first()
    )


def get_effective_salary_revision(salary_setup: SalarySetup, on_date: date):
    return (
        salary_setup.revisions.filter(effective_from__lte=on_date)
        .filter(models.Q(effective_to__isnull=True) | models.Q(effective_to__gte=on_date))
        .order_by("-effective_from", "-created_at")
        .first()
    )


def get_unpaid_leave_days(employee, year: int, month: int) -> Decimal:
    try:
        from leaves.models import LeaveRequest
    except Exception:
        return Decimal("0")

    month_start = date(year, month, 1)
    month_end = date(year, month, monthrange(year, month)[1])
    value = (
        LeaveRequest.objects.filter(
            employee=employee,
            status=LeaveRequest.StatusChoices.APPROVED,
            leave_type__is_paid=False,
            from_date__lte=month_end,
            to_date__gte=month_start,
        ).aggregate(total=Sum("number_of_days"))["total"]
        or Decimal("0")
    )
    return q(value)


def create_or_update_payslip_for_run(payroll_run: PayrollRun, employee, created_by=None):
    on_date = payroll_run.period_end
    salary_setup = getattr(employee, "salary_setup", None)
    if not salary_setup or not salary_setup.is_active:
        return None

    revision = get_effective_salary_revision(salary_setup, on_date)
    source = revision or salary_setup
    setup = salary_setup

    base_gross = q(getattr(source, "gross_salary", None) or (
        source.basic_salary
        + source.house_rent_allowance
        + source.conveyance_allowance
        + source.medical_allowance
        + source.other_allowance
    ))

    payslip, _ = Payslip.objects.get_or_create(
        payroll_run=payroll_run,
        employee=employee,
        defaults={"salary_revision": revision},
    )
    payslip.salary_revision = revision

    overtime_amount = q((payslip.overtime_hours or Decimal("0")) * (payslip.overtime_rate or Decimal("0")))
    unpaid_days = payslip.unpaid_leave_days if payslip.unpaid_leave_days > 0 else get_unpaid_leave_days(employee, payroll_run.year, payroll_run.month)
    unpaid_deduction = q((base_gross / DAYS_IN_MONTH_STANDARD) * unpaid_days)

    taxable = q(
        base_gross
        + overtime_amount
        + (payslip.bonus or Decimal("0"))
        + (payslip.adjustment_addition or Decimal("0"))
        - unpaid_deduction
        - (payslip.adjustment_deduction or Decimal("0"))
    )

    income_tax = calculate_monthly_tax(taxable, on_date=on_date)
    policy = get_statutory_policy(on_date)

    eobi = Decimal("0")
    pf = Decimal("0")
    social_security = Decimal("0")
    other_statutory = Decimal("0")
    employer_pf = Decimal("0")

    if policy:
        eobi = q(policy.eobi_employee_fixed)
        pf = q(taxable * policy.provident_fund_employee_percent / Decimal("100"))
        employer_pf = q(taxable * policy.provident_fund_employer_percent / Decimal("100"))
        social_security = q(policy.social_security_fixed)
        other_statutory = q(policy.other_statutory_fixed)

    fixed_deductions = q(
        (setup.loan_installment or Decimal("0"))
        + (setup.advance_salary_repayment or Decimal("0"))
        + (setup.eobi_contribution or Decimal("0"))
        + (setup.pessi_contribution or Decimal("0"))
        + (setup.gratuity_deduction or Decimal("0"))
        + (setup.provident_fund_deduction or Decimal("0"))
        + (setup.misc_deduction or Decimal("0"))
    )

    total_deductions = q(
        income_tax
        + eobi
        + pf
        + social_security
        + other_statutory
        + unpaid_deduction
        + (payslip.adjustment_deduction or Decimal("0"))
        + fixed_deductions
    )
    net_salary = q(
        taxable
        - income_tax
        - eobi
        - pf
        - social_security
        - other_statutory
        - fixed_deductions
    )
    employer_contribution = employer_pf
    total_employer_cost = q(base_gross + overtime_amount + (payslip.bonus or Decimal("0")) + (payslip.adjustment_addition or Decimal("0")) + employer_contribution)

    payslip.unpaid_leave_days = unpaid_days
    payslip.unpaid_leave_deduction = unpaid_deduction
    payslip.gross_salary = base_gross
    payslip.taxable_salary = taxable
    payslip.income_tax = income_tax
    payslip.eobi = eobi
    payslip.provident_fund = pf
    payslip.social_security = social_security
    payslip.other_statutory = other_statutory
    payslip.total_deductions = total_deductions
    payslip.net_salary = net_salary
    payslip.employer_contribution = employer_contribution
    payslip.total_employer_cost = total_employer_cost
    payslip.save()
    return payslip


def generate_payslips(payroll_run: PayrollRun, created_by=None) -> int:
    employees = SalarySetup.objects.filter(is_active=True, employee__employment_status="Active").select_related("employee")
    generated = 0
    for setup in employees:
        payslip = create_or_update_payslip_for_run(payroll_run=payroll_run, employee=setup.employee, created_by=created_by)
        if payslip:
            generated += 1
    return generated
