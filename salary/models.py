from calendar import monthrange
import calendar
from datetime import date, datetime
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from accounts.models import EmployeeProfile


class TaxYear(models.Model):
    fiscal_year = models.CharField(
        max_length=20, unique=True, help_text="e.g. 2025-2026"
    )
    effective_from = models.DateField()
    effective_to = models.DateField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-effective_from"]
        verbose_name = "Tax Year"
        verbose_name_plural = "Tax Years"
        constraints = [
            models.CheckConstraint(
                check=models.Q(effective_to__isnull=True) | models.Q(effective_to__gte=models.F("effective_from")),
                name="tax_year_effective_to_gte_from",
            ),
        ]

    def __str__(self) -> str:
        return self.fiscal_year

    def clean(self) -> None:
        if self.effective_to and self.effective_to < self.effective_from:
            raise ValidationError({"effective_to": "Effective to must be on or after effective from."})


class SalaryTaxSlab(models.Model):
    tax_year = models.ForeignKey(
        TaxYear, on_delete=models.CASCADE, related_name="slabs"
    )
    name = models.CharField(max_length=120)
    annual_min_income = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    annual_max_income = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True)
    taxable_excess_over = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    base_tax = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    rate_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_order", "annual_min_income"]
        constraints = [
            models.CheckConstraint(
                check=models.Q(annual_max_income__isnull=True)
                | models.Q(annual_max_income__gte=models.F("annual_min_income")),
                name="salary_tax_slab_annual_max_gte_min",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.tax_year})"

    def clean(self) -> None:
        errors = {}
        if self.annual_min_income is not None and self.annual_min_income < 0:
            errors["annual_min_income"] = "Annual minimum income cannot be negative."
        if self.annual_max_income is not None and self.annual_max_income < 0:
            errors["annual_max_income"] = "Annual maximum income cannot be negative."
        if self.annual_max_income is not None and self.annual_max_income < self.annual_min_income:
            errors["annual_max_income"] = "Annual maximum income must be greater than or equal to annual minimum income."
        if self.taxable_excess_over is not None and self.taxable_excess_over < 0:
            errors["taxable_excess_over"] = "Taxable excess threshold cannot be negative."
        if self.base_tax is not None and self.base_tax < 0:
            errors["base_tax"] = "Base tax cannot be negative."
        if self.rate_percent is not None and self.rate_percent < 0:
            errors["rate_percent"] = "Rate percent cannot be negative."
        if errors:
            raise ValidationError(errors)


class StatutoryDeductionPolicy(models.Model):
    name = models.CharField(max_length=120)
    effective_from = models.DateField()
    effective_to = models.DateField(blank=True, null=True)
    eobi_employee_fixed = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    provident_fund_employee_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    provident_fund_employer_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    social_security_fixed = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    other_statutory_fixed = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-effective_from", "name"]
        constraints = [
            models.CheckConstraint(
                check=models.Q(effective_to__isnull=True) | models.Q(effective_to__gte=models.F("effective_from")),
                name="statutory_policy_effective_to_gte_from",
            )
        ]

    def __str__(self) -> str:
        return self.name


class SalarySetup(models.Model):
    employee = models.OneToOneField(
        EmployeeProfile,
        on_delete=models.CASCADE,
        related_name="salary_setup",
    )
    gross_salary_input = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    basic_salary = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    house_rent_allowance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    utility_allowance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    conveyance_allowance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    medical_allowance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    other_allowance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_working_days = models.PositiveSmallIntegerField(default=30)
    currency = models.CharField(max_length=10, default="PKR")
    ntn_no = models.CharField(max_length=50, blank=True)
    payment_mode = models.CharField(
        max_length=20,
        choices=EmployeeProfile.PaymentModeChoices.choices,
        default=EmployeeProfile.PaymentModeChoices.BANK,
    )
    bank_name = models.CharField(max_length=120, blank=True)
    account_title = models.CharField(max_length=120, blank=True)
    account_number = models.CharField(max_length=50, blank=True)
    general_total_loan = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    general_paid_loan = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    general_balance_loan = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    pf_total_loan = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    pf_paid_loan = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    pf_balance_loan = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    pf_starting_balance_own = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    pf_starting_balance_company = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    pf_record_date = models.DateField(blank=True, null=True)
    pf_permanent_loan_own = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    pf_permanent_loan_company = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    pf_refundable_loan_own = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    pf_refundable_loan_company = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    absent_days = models.DecimalField(max_digits=7, decimal_places=2, default=0)
    unpaid_days = models.DecimalField(max_digits=7, decimal_places=2, default=0)
    loan_installment = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    advance_salary_repayment = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    eobi_contribution = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    pessi_contribution = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    gratuity_deduction = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    provident_fund_deduction = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    misc_deduction = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["employee__full_name"]

    def __str__(self) -> str:
        return f"{self.employee.full_name} salary setup"

    @property
    def gross_salary(self) -> Decimal:
        if self.gross_salary_input and self.gross_salary_input > 0:
            return self.gross_salary_input
        return (
            (self.basic_salary or Decimal("0"))
            + (self.house_rent_allowance or Decimal("0"))
            + (self.utility_allowance or Decimal("0"))
            + (self.conveyance_allowance or Decimal("0"))
            + (self.medical_allowance or Decimal("0"))
            + (self.other_allowance or Decimal("0"))
        )

    @property
    def active_revision(self):
        today = date.today()
        return (
            self.revisions.filter(effective_from__lte=today)
            .filter(models.Q(effective_to__isnull=True) | models.Q(effective_to__gte=today))
            .order_by("-effective_from")
            .first()
        )

    def clean(self) -> None:
        errors = {}
        component_fields = [
            "gross_salary_input",
            "basic_salary",
            "house_rent_allowance",
            "utility_allowance",
            "conveyance_allowance",
            "medical_allowance",
            "other_allowance",
            "absent_days",
            "unpaid_days",
            "loan_installment",
            "advance_salary_repayment",
            "eobi_contribution",
            "pessi_contribution",
            "gratuity_deduction",
            "provident_fund_deduction",
            "misc_deduction",
        ]
        for field_name in component_fields:
            value = getattr(self, field_name)
            if value is not None and value < 0:
                errors[field_name] = "Value cannot be negative."

        if self.unpaid_days and self.total_working_days and self.unpaid_days > self.total_working_days:
            errors["unpaid_days"] = "Unpaid days cannot be greater than total working days."

        if self.payment_mode == EmployeeProfile.PaymentModeChoices.BANK:
            if not self.bank_name:
                errors["bank_name"] = "Bank name is required for bank payments."
            if not self.account_title:
                errors["account_title"] = "Account title is required for bank payments."
            if not self.account_number:
                errors["account_number"] = "Account number is required for bank payments."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        should_auto_fill = (
            self.gross_salary_input
            and self.gross_salary_input > 0
            and (self.basic_salary or Decimal("0")) == 0
            and (self.house_rent_allowance or Decimal("0")) == 0
            and (self.utility_allowance or Decimal("0")) == 0
            and (self.medical_allowance or Decimal("0")) == 0
        )
        if should_auto_fill:
            self.basic_salary = (self.gross_salary_input * Decimal("0.60")).quantize(Decimal("0.01"))
            self.house_rent_allowance = (self.gross_salary_input * Decimal("0.20")).quantize(Decimal("0.01"))
            self.utility_allowance = (self.gross_salary_input * Decimal("0.10")).quantize(Decimal("0.01"))
            self.medical_allowance = (self.gross_salary_input * Decimal("0.10")).quantize(Decimal("0.01"))
        super().save(*args, **kwargs)


class SalaryRevision(models.Model):
    salary_setup = models.ForeignKey(
        SalarySetup,
        on_delete=models.CASCADE,
        related_name="revisions",
    )
    effective_from = models.DateField()
    effective_to = models.DateField(blank=True, null=True)
    basic_salary = models.DecimalField(max_digits=12, decimal_places=2)
    house_rent_allowance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    conveyance_allowance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    medical_allowance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    other_allowance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    payment_mode = models.CharField(max_length=20, choices=EmployeeProfile.PaymentModeChoices.choices)
    bank_name = models.CharField(max_length=120, blank=True)
    account_title = models.CharField(max_length=120, blank=True)
    account_number = models.CharField(max_length=50, blank=True)
    reason = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="created_salary_revisions",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-effective_from", "-created_at"]

    def __str__(self) -> str:
        return f"{self.salary_setup.employee.full_name} ({self.effective_from})"

    @property
    def gross_salary(self) -> Decimal:
        return (
            (self.basic_salary or Decimal("0"))
            + (self.house_rent_allowance or Decimal("0"))
            + (self.conveyance_allowance or Decimal("0"))
            + (self.medical_allowance or Decimal("0"))
            + (self.other_allowance or Decimal("0"))
        )


class PayrollRun(models.Model):
    class StatusChoices(models.TextChoices):
        DRAFT = "Draft", "Draft"
        PENDING_APPROVAL = "Pending Approval", "Pending Approval"
        APPROVED = "Approved", "Approved"
        POSTED = "Posted", "Posted"
        LOCKED = "Locked", "Locked"

    MONTH_CHOICES = [(i, calendar.month_name[i]) for i in range(1, 13)]

    year = models.PositiveIntegerField()
    month = models.PositiveSmallIntegerField(choices=MONTH_CHOICES, default=date.today().month)
    status = models.CharField(max_length=30, choices=StatusChoices.choices, default=StatusChoices.DRAFT)
    generated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="generated_payroll_runs",
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="approved_payroll_runs",
    )
    approved_at = models.DateTimeField(blank=True, null=True)
    posted_at = models.DateTimeField(blank=True, null=True)
    locked_at = models.DateTimeField(blank=True, null=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-year", "-month", "-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["year", "month"], name="unique_payroll_run_year_month"),
            models.CheckConstraint(check=models.Q(month__gte=1) & models.Q(month__lte=12), name="payroll_run_month_1_12"),
        ]

    def __str__(self) -> str:
        return f"Payroll {self.year}-{self.month:02d}"

    @property
    def period_start(self) -> date:
        # Pay cycle runs 23rd of previous month → 22nd of current month
        if self.month == 1:
            return date(self.year - 1, 12, 23)
        return date(self.year, self.month - 1, 23)

    @property
    def period_end(self) -> date:
        return date(self.year, self.month, 22)


class Payslip(models.Model):
    class StatusChoices(models.TextChoices):
        DRAFT = "Draft", "Draft"
        FINALIZED = "Finalized", "Finalized"

    payroll_run = models.ForeignKey(PayrollRun, on_delete=models.CASCADE, related_name="payslips")
    employee = models.ForeignKey(EmployeeProfile, on_delete=models.CASCADE, related_name="payslips")
    salary_revision = models.ForeignKey(
        SalaryRevision,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="payslips",
    )

    overtime_hours = models.DecimalField(max_digits=7, decimal_places=2, default=0)
    overtime_rate = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    bonus = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    adjustment_addition = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    adjustment_deduction = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    unpaid_leave_days = models.DecimalField(max_digits=7, decimal_places=2, default=0)
    unpaid_leave_deduction = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    gross_salary = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    taxable_salary = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    income_tax = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    eobi = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    provident_fund = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    social_security = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    other_statutory = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_deductions = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    net_salary = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    employer_contribution = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_employer_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    is_paid = models.BooleanField(default=False)
    paid_at = models.DateTimeField(blank=True, null=True)
    paid_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="paid_payslips",
    )

    status = models.CharField(max_length=20, choices=StatusChoices.choices, default=StatusChoices.DRAFT)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="approved_payslips",
    )
    approved_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["employee__full_name"]
        constraints = [models.UniqueConstraint(fields=["payroll_run", "employee"], name="unique_payslip_per_run_employee")]

    def __str__(self) -> str:
        return f"{self.employee.full_name} - {self.payroll_run}"

    @property
    def overtime_amount(self) -> Decimal:
        return (self.overtime_hours or Decimal("0")) * (self.overtime_rate or Decimal("0"))

    @property
    def total_additions(self) -> Decimal:
        return self.overtime_amount + (self.bonus or Decimal("0")) + (self.adjustment_addition or Decimal("0"))

    def clean(self) -> None:
        errors = {}
        if self.payroll_run and self.payroll_run.status == PayrollRun.StatusChoices.LOCKED:
            errors["payroll_run"] = "Cannot edit payslip in a locked payroll run."
        if errors:
            raise ValidationError(errors)
