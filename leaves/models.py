from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Sum

from accounts.models import EmployeeProfile


class LeaveType(models.Model):
    name = models.CharField(max_length=120, unique=True)
    is_paid = models.BooleanField(default=True)
    is_wfh = models.BooleanField(
        default=False,
        verbose_name="Work from Home type",
        help_text=(
            "When enabled, requests use the monthly WFH balance (2 days/month, max 5) "
            "instead of a standard leave allocation."
        ),
    )
    default_days = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    requires_attachment = models.BooleanField(default=False)
    available_for_probation = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        suffix = "Paid" if self.is_paid else "Unpaid"
        return f"{self.name} ({suffix})"


class WFHPolicy(models.Model):
    """
    Singleton — one record configures the entire company WFH policy.
    Use WFHPolicy.get() to read the current policy safely.
    """

    is_enabled = models.BooleanField(
        default=True,
        verbose_name="WFH programme enabled",
        help_text="Turn off to disable WFH applications company-wide.",
    )
    monthly_accrual_days = models.DecimalField(
        max_digits=4, decimal_places=2, default=Decimal("2"),
        verbose_name="Days accrued per month",
        help_text="How many WFH days each employee earns every calendar month.",
    )
    max_balance = models.DecimalField(
        max_digits=4, decimal_places=2, default=Decimal("5"),
        verbose_name="Maximum balance (cap)",
        help_text="Maximum WFH days an employee can accumulate at any one time.",
    )
    rollover_enabled = models.BooleanField(
        default=True,
        verbose_name="Unused days roll over",
        help_text=(
            "When ON, unused WFH days carry forward to the next month (up to the cap). "
            "When OFF, the balance resets to the monthly accrual at the start of each month."
        ),
    )
    max_days_per_request = models.DecimalField(
        max_digits=4, decimal_places=2, default=Decimal("5"),
        verbose_name="Max days per single request",
        help_text="Maximum number of WFH days an employee can request in one go.",
    )
    notes = models.TextField(
        blank=True,
        verbose_name="Policy notes",
        help_text="Internal notes about the WFH policy (not shown to employees).",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "WFH Policy"
        verbose_name_plural = "WFH Policy"

    def __str__(self) -> str:
        status = "Enabled" if self.is_enabled else "Disabled"
        return f"WFH Policy ({status} — {self.monthly_accrual_days} days/month, max {self.max_balance})"

    def save(self, *args, **kwargs):
        # Enforce singleton — always use pk=1
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def get(cls) -> "WFHPolicy":
        """Return the current policy, creating defaults if none exists."""
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def clean(self):
        from django.core.exceptions import ValidationError
        errors = {}
        if self.monthly_accrual_days is not None and self.monthly_accrual_days <= 0:
            errors["monthly_accrual_days"] = "Accrual days must be greater than zero."
        if self.max_balance is not None and self.max_balance <= 0:
            errors["max_balance"] = "Maximum balance must be greater than zero."
        if (
            self.monthly_accrual_days and self.max_balance
            and self.monthly_accrual_days > self.max_balance
        ):
            errors["monthly_accrual_days"] = "Monthly accrual cannot exceed the maximum balance cap."
        if self.max_days_per_request is not None and self.max_days_per_request <= 0:
            errors["max_days_per_request"] = "Max days per request must be greater than zero."
        if errors:
            raise ValidationError(errors)


class WFHBalance(models.Model):
    """Monthly-accruing WFH balance per employee. Settings are read from WFHPolicy."""

    employee = models.OneToOneField(
        EmployeeProfile,
        on_delete=models.CASCADE,
        related_name="wfh_balance",
    )
    balance = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    last_accrued_year = models.PositiveIntegerField(null=True, blank=True)
    last_accrued_month = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "WFH Balance"
        verbose_name_plural = "WFH Balances"
        ordering = ["employee__full_name"]

    def __str__(self) -> str:
        return f"{self.employee.full_name} — WFH balance: {self.balance}"

    def accrue(self, as_of_date=None) -> Decimal:
        """
        Add policy.monthly_accrual_days for each unaccrued month, capped at policy.max_balance.
        If rollover is disabled, balance resets to the monthly accrual each month.
        Called lazily whenever the balance is needed.
        """
        from datetime import date
        from django.utils import timezone

        today = as_of_date or timezone.localdate()
        policy = WFHPolicy.get()

        if not policy.is_enabled:
            return self.balance

        monthly = policy.monthly_accrual_days
        cap = policy.max_balance

        if self.last_accrued_year is None:
            self.balance = min(cap, self.balance + monthly)
            self.last_accrued_year = today.year
            self.last_accrued_month = today.month
            self.save(update_fields=["balance", "last_accrued_year", "last_accrued_month", "updated_at"])
            return self.balance

        last = date(self.last_accrued_year, self.last_accrued_month, 1)
        current = date(today.year, today.month, 1)
        months_due = (current.year - last.year) * 12 + (current.month - last.month)

        if months_due <= 0:
            return self.balance

        new_balance = self.balance
        for _ in range(months_due):
            if policy.rollover_enabled:
                new_balance = min(cap, new_balance + monthly)
            else:
                # No rollover — reset to this month's allowance only
                new_balance = monthly

        self.balance = new_balance
        self.last_accrued_year = today.year
        self.last_accrued_month = today.month
        self.save(update_fields=["balance", "last_accrued_year", "last_accrued_month", "updated_at"])
        return self.balance

    @property
    def pending_days(self) -> Decimal:
        """Days in in-flight (pending / manager-approved) WFH requests, not yet approved."""
        return (
            LeaveRequest.objects.filter(
                employee=self.employee,
                leave_type__is_wfh=True,
                status__in=[
                    LeaveRequest.StatusChoices.PENDING,
                    LeaveRequest.StatusChoices.MANAGER_APPROVED,
                ],
            ).aggregate(total=Sum("number_of_days"))["total"]
            or Decimal("0")
        )

    @property
    def available_days(self) -> Decimal:
        """Balance minus pending requests — what the employee can still book."""
        return max(Decimal("0"), self.balance - self.pending_days)

    def deduct(self, days: Decimal) -> None:
        """Called when a WFH request is approved."""
        self.balance = max(Decimal("0"), self.balance - days)
        self.save(update_fields=["balance", "updated_at"])

    def restore(self, days: Decimal) -> None:
        """Called when an approved WFH request is rejected or cancelled."""
        cap = WFHPolicy.get().max_balance
        self.balance = min(cap, self.balance + days)
        self.save(update_fields=["balance", "updated_at"])


class LeaveAllocation(models.Model):
    employee = models.ForeignKey(
        EmployeeProfile,
        on_delete=models.CASCADE,
        related_name="leave_allocations",
    )
    leave_type = models.ForeignKey(
        LeaveType,
        on_delete=models.CASCADE,
        related_name="allocations",
    )
    year = models.PositiveIntegerField()
    allocated_days = models.DecimalField(max_digits=6, decimal_places=2)
    carry_forward_days = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-year", "employee__full_name", "leave_type__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["employee", "leave_type", "year"],
                name="unique_leave_allocation_per_year",
            )
        ]

    def __str__(self) -> str:
        return f"{self.employee.full_name} - {self.leave_type.name} - {self.year}"

    @property
    def total_available_days(self) -> Decimal:
        return (self.allocated_days or Decimal("0")) + (self.carry_forward_days or Decimal("0"))

    @property
    def booked_days(self) -> Decimal:
        total = self.leave_requests.filter(
            status__in=[
                LeaveRequest.StatusChoices.PENDING,
                LeaveRequest.StatusChoices.MANAGER_APPROVED,
                LeaveRequest.StatusChoices.APPROVED,
            ]
        ).aggregate(total=Sum("number_of_days"))["total"]
        return total or Decimal("0")

    @property
    def remaining_days(self) -> Decimal:
        return self.total_available_days - self.booked_days

    def clean(self) -> None:
        errors = {}
        if (
            self.employee
            and self.employee.employment_status == EmployeeProfile.EmploymentStatusChoices.INACTIVE
        ):
            errors["employee"] = "Inactive employees cannot receive leave allocations."
        if self.allocated_days is not None and self.allocated_days < 0:
            errors["allocated_days"] = "Allocated days cannot be negative."
        if self.carry_forward_days is not None and self.carry_forward_days < 0:
            errors["carry_forward_days"] = "Carry forward days cannot be negative."
        if errors:
            raise ValidationError(errors)


class LeaveRequest(models.Model):
    class StatusChoices(models.TextChoices):
        PENDING = "Pending", "Pending"
        MANAGER_APPROVED = "Manager Approved", "Manager Approved"
        APPROVED = "Approved", "Approved"
        REJECTED = "Rejected", "Rejected"
        CANCELLED = "Cancelled", "Cancelled"

    employee = models.ForeignKey(
        EmployeeProfile,
        on_delete=models.CASCADE,
        related_name="leave_requests",
    )
    leave_type = models.ForeignKey(
        LeaveType,
        on_delete=models.PROTECT,
        related_name="leave_requests",
    )
    allocation = models.ForeignKey(
        LeaveAllocation,
        on_delete=models.PROTECT,
        related_name="leave_requests",
        blank=True,
        null=True,
    )
    from_date = models.DateField()
    to_date = models.DateField()
    number_of_days = models.DecimalField(max_digits=6, decimal_places=2, default=1)
    attachment = models.FileField(upload_to="leave_requests/attachments/", blank=True, null=True)
    reason = models.TextField(blank=True)
    status = models.CharField(
        max_length=20,
        choices=StatusChoices.choices,
        default=StatusChoices.PENDING,
    )
    remarks = models.TextField(blank=True)
    created_by = models.ForeignKey(
        EmployeeProfile,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="created_leave_requests",
    )
    manager_approved_by = models.ForeignKey(
        EmployeeProfile,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="manager_approved_leave_requests",
        verbose_name="Manager Approved By",
    )
    approved_by = models.ForeignKey(
        EmployeeProfile,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="approved_leave_requests",
        verbose_name="Admin Approved By",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-from_date", "-created_at"]

    def __str__(self) -> str:
        return f"{self.employee.full_name} - {self.leave_type.name} ({self.from_date} to {self.to_date})"

    def clean(self) -> None:
        errors = {}
        if self.to_date and self.from_date and self.to_date < self.from_date:
            errors["to_date"] = "End date cannot be earlier than the start date."

        if self.employee and self.employee.employment_status == EmployeeProfile.EmploymentStatusChoices.INACTIVE:
            errors["employee"] = "Inactive employees cannot request leave."

        if self.leave_type and self.leave_type.requires_attachment and not self.attachment:
            errors["attachment"] = "Attachment is required for this leave type."

        if self.employee and self.leave_type and self.from_date:
            if self.leave_type.is_wfh:
                # WFH uses monthly balance and the company policy, not a standard allocation
                policy = WFHPolicy.get()
                if not policy.is_enabled:
                    errors["leave_type"] = "Work From Home is currently disabled by the company."
                else:
                    wfh_bal, _ = WFHBalance.objects.get_or_create(employee=self.employee)
                    wfh_bal.accrue()
                    if self.number_of_days <= 0:
                        errors["number_of_days"] = "WFH days must be greater than zero."
                    elif self.number_of_days > policy.max_days_per_request:
                        errors["number_of_days"] = (
                            f"Cannot request more than {policy.max_days_per_request} WFH day(s) at once."
                        )
                    else:
                        pending = (
                            LeaveRequest.objects.filter(
                                employee=self.employee,
                                leave_type=self.leave_type,
                                status__in=[
                                    self.StatusChoices.PENDING,
                                    self.StatusChoices.MANAGER_APPROVED,
                                ],
                            ).exclude(pk=self.pk or 0)
                            .aggregate(total=Sum("number_of_days"))["total"]
                            or Decimal("0")
                        )
                        available = wfh_bal.balance - pending
                        if self.number_of_days > available:
                            errors["number_of_days"] = (
                                f"Insufficient WFH balance. Available: {available} day(s)."
                            )
            else:
                allocation = LeaveAllocation.objects.filter(
                    employee=self.employee,
                    leave_type=self.leave_type,
                    year=self.from_date.year,
                ).first()
                if not allocation:
                    errors["leave_type"] = "No leave allocation exists for this employee and leave type."
                else:
                    self.allocation = allocation
                    if self.number_of_days <= 0:
                        errors["number_of_days"] = "Leave days must be greater than zero."
                    else:
                        booked = allocation.booked_days
                        in_flight = [self.StatusChoices.PENDING, self.StatusChoices.MANAGER_APPROVED, self.StatusChoices.APPROVED]
                        if self.pk and self.status in in_flight:
                            current = LeaveRequest.objects.filter(pk=self.pk).first()
                            if current and current.status in in_flight:
                                booked -= current.number_of_days
                        if booked + self.number_of_days > allocation.total_available_days:
                            errors["number_of_days"] = "Requested leave exceeds the available allocation."

        if errors:
            raise ValidationError(errors)


# ─── Short Leave ──────────────────────────────────────────────────────────────

class ShortLeavePolicy(models.Model):
    """Singleton — company-wide short leave settings."""

    is_enabled = models.BooleanField(default=True, verbose_name="Short leave enabled")
    max_per_month = models.PositiveSmallIntegerField(
        default=2, verbose_name="Max short leaves per month",
        help_text="Maximum short leave requests per employee per calendar month.",
    )
    min_hours_before_afternoon = models.DecimalField(
        max_digits=4, decimal_places=2, default=Decimal("4"),
        verbose_name="Min hours worked before afternoon short leave",
        help_text="Employee must have checked in and worked at least this many hours before applying.",
    )
    notes = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Short Leave Policy"
        verbose_name_plural = "Short Leave Policy"

    def __str__(self) -> str:
        return f"Short Leave Policy — max {self.max_per_month}/month"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def get(cls) -> "ShortLeavePolicy":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class ShortLeaveRequest(models.Model):
    class PeriodChoices(models.TextChoices):
        MORNING   = "Morning",   "Morning (late start)"
        AFTERNOON = "Afternoon", "Afternoon (early leaving)"

    class StatusChoices(models.TextChoices):
        PENDING          = "Pending",          "Pending"
        MANAGER_APPROVED = "Manager Approved", "Manager Approved"
        APPROVED         = "Approved",         "Approved"
        REJECTED         = "Rejected",         "Rejected"
        CANCELLED        = "Cancelled",        "Cancelled"

    employee = models.ForeignKey(
        EmployeeProfile, on_delete=models.CASCADE, related_name="short_leave_requests",
    )
    date      = models.DateField()
    period    = models.CharField(max_length=20, choices=PeriodChoices.choices)
    from_time = models.TimeField()
    to_time   = models.TimeField()
    reason    = models.TextField(blank=True)
    status    = models.CharField(max_length=20, choices=StatusChoices.choices, default=StatusChoices.PENDING)
    remarks   = models.TextField(blank=True)
    manager_approved_by = models.ForeignKey(
        EmployeeProfile, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="manager_approved_short_leaves",
    )
    approved_by = models.ForeignKey(
        EmployeeProfile, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="approved_short_leaves",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date", "-created_at"]
        verbose_name = "Short Leave Request"
        verbose_name_plural = "Short Leave Requests"

    def __str__(self) -> str:
        return f"{self.employee.full_name} — {self.period} short leave on {self.date}"

    @property
    def duration_hours(self) -> Decimal:
        from datetime import datetime, date as _d
        start = datetime.combine(_d.today(), self.from_time)
        end   = datetime.combine(_d.today(), self.to_time)
        return Decimal(str(round((end - start).seconds / 3600, 2)))
