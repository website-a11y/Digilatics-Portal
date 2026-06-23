from django.conf import settings
from django.db import models


class EmployeeProfile(models.Model):
    class GenderChoices(models.TextChoices):
        MALE = "Male", "Male"
        FEMALE = "Female", "Female"
        OTHER = "Other", "Other"
        PREFER_NOT_TO_SAY = "Prefer not to say", "Prefer not to say"

    class MaritalStatusChoices(models.TextChoices):
        SINGLE = "Single", "Single"
        MARRIED = "Married", "Married"
        DIVORCED = "Divorced", "Divorced"
        WIDOWED = "Widowed", "Widowed"

    class EmploymentTypeChoices(models.TextChoices):
        PERMANENT = "Permanent", "Permanent"
        PROBATION = "Probation", "Probation"
        CONTRACT = "Contract", "Contract"
        INTERN = "Intern", "Intern"

    class EmploymentStatusChoices(models.TextChoices):
        ACTIVE = "Active", "Active"
        ONBOARDING = "Onboarding", "Onboarding"
        INACTIVE = "Inactive", "Inactive"
        ON_LEAVE = "On Leave", "On Leave"

    class PaymentModeChoices(models.TextChoices):
        BANK = "Bank", "Bank"
        CASH = "Cash", "Cash"
        CHEQUE = "Cheque", "Cheque"
        ONLINE_TRANSFER = "Online Transfer", "Online Transfer"
        OTHER = "Other", "Other"
        DASH = "-", "-"

    class RoleChoices(models.TextChoices):
        EMPLOYEE = "Employee", "Employee"
        MANAGER = "Manager", "Manager"
        APPROVER = "Approver", "Approver"
        SUPER_ADMIN = "Super Admin", "Super Admin"

    full_name = models.CharField(max_length=200)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="employee_profile",
    )
    profile_photo = models.ImageField(
        upload_to="employee_profiles/photos/",
        blank=True,
        null=True,
    )
    gender = models.CharField(
        max_length=30,
        choices=GenderChoices.choices,
        blank=True,
    )
    date_of_birth = models.DateField(blank=True, null=True)
    marital_status = models.CharField(
        max_length=20,
        choices=MaritalStatusChoices.choices,
        blank=True,
    )

    personal_email = models.EmailField(blank=True)
    official_email = models.EmailField(unique=True)
    personal_phone = models.CharField(max_length=25)
    emergency_contact_name = models.CharField(max_length=150, blank=True)
    emergency_contact_number = models.CharField(max_length=25, blank=True)
    current_address = models.TextField(blank=True)
    city = models.CharField(max_length=120, blank=True)
    country = models.CharField(max_length=120, blank=True)

    cnic = models.CharField("CNIC / National ID", max_length=50, blank=True, default="")
    passport_number = models.CharField(max_length=50, blank=True)

    employee_code = models.CharField(max_length=30, unique=True)
    department = models.CharField(max_length=120)
    designation = models.CharField(max_length=120)
    employment_type = models.CharField(
        max_length=20,
        choices=EmploymentTypeChoices.choices,
    )
    employment_status = models.CharField(
        max_length=20,
        choices=EmploymentStatusChoices.choices,
        default=EmploymentStatusChoices.ACTIVE,
    )
    joining_date = models.DateField()
    hire_date = models.DateField(blank=True, null=True)
    confirmation_date = models.DateField(blank=True, null=True)
    reporting_manager = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="team_members",
    )
    team = models.CharField(max_length=120, blank=True)
    work_location = models.CharField(max_length=120, blank=True)
    shift = models.CharField(max_length=80, blank=True)
    shift_master = models.ForeignKey(
        "attendance.Shift",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="employees",
        verbose_name="Shift",
        help_text="Assign a shift template — check-in/out times sync automatically.",
    )
    scheduled_checkin = models.TimeField(
        null=True,
        blank=True,
        verbose_name="Scheduled Check-in",
        help_text="Auto-filled from Shift. Override only when no shift is assigned.",
    )
    scheduled_checkout = models.TimeField(
        null=True,
        blank=True,
        verbose_name="Scheduled Check-out",
        help_text="Auto-filled from Shift. Override only when no shift is assigned.",
    )

    basic_salary = models.DecimalField(max_digits=12, decimal_places=2)
    house_rent_allowance = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
    )
    conveyance_allowance = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
    )
    medical_allowance = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
    )
    other_allowance = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
    )
    payment_mode = models.CharField(
        max_length=20,
        choices=PaymentModeChoices.choices,
        default=PaymentModeChoices.BANK,
    )

    bank_name = models.CharField(max_length=120, blank=True)
    account_title = models.CharField(max_length=120, blank=True)
    account_number = models.CharField(max_length=50, blank=True)
    iban = models.CharField(max_length=80, blank=True)

    role = models.CharField(
        max_length=20,
        choices=RoleChoices.choices,
        default=RoleChoices.EMPLOYEE,
    )

    cnic_copy = models.FileField(
        upload_to="employee_profiles/documents/cnic/",
        blank=True,
        null=True,
    )
    resume = models.FileField(
        upload_to="employee_profiles/documents/resumes/",
        blank=True,
        null=True,
    )
    offer_letter = models.FileField(
        upload_to="employee_profiles/documents/offer_letters/",
        blank=True,
        null=True,
    )
    contract = models.FileField(
        upload_to="employee_profiles/documents/contracts/",
        blank=True,
        null=True,
    )

    remarks = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="created_employee_profiles",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Employee registration"
        verbose_name_plural = "Employee registrations"
        ordering = ["full_name", "employee_code"]
        permissions = [
            ("can_manage_team", "Can manage team records"),
            ("can_approve_employee_records", "Can approve employee records"),
            ("can_view_employee_directory", "Can view employee directory"),
        ]

    def __str__(self) -> str:
        return f"{self.full_name} ({self.employee_code})"

    def save(self, *args, **kwargs):
        if self.shift_master_id:
            self.scheduled_checkin = self.shift_master.start_time
            self.scheduled_checkout = self.shift_master.end_time
        super().save(*args, **kwargs)

    @property
    def uploaded_documents_count(self) -> int:
        return sum(
            bool(document)
            for document in (
                self.cnic_copy,
                self.resume,
                self.offer_letter,
                self.contract,
            )
        )


class Department(models.Model):
    """HR-managed list of departments shown in the employee form dropdown."""
    name = models.CharField(max_length=120, unique=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Designation(models.Model):
    """HR-managed list of designations shown in the employee form dropdown."""
    name = models.CharField(max_length=120, unique=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name
