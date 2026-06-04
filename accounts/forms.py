from datetime import time as time_type

from django import forms
from django.contrib.auth import get_user_model, password_validation
from django.core.exceptions import ValidationError
from django.urls import reverse

from .models import EmployeeProfile
from teams.models import Team


User = get_user_model()


class EmployeeProfileAdminForm(forms.ModelForm):
    department = forms.ChoiceField(required=False)
    username = forms.CharField(max_length=150, required=True)
    first_name = forms.CharField(max_length=150, required=False)
    last_name = forms.CharField(max_length=150, required=False)
    password = forms.CharField(
        required=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        help_text="Required when creating a user. Leave blank to keep the current password.",
    )
    send_setup_email = forms.BooleanField(
        required=False,
        initial=True,
        label="Send password setup email",
        help_text=(
            "When checked, the employee will receive an email with a secure link to set "
            "their own password. Leave the password field blank to use this option."
        ),
    )

    class Meta:
        model = EmployeeProfile
        exclude = ("user", "created_by", "created_at", "updated_at")
        widgets = {
            "date_of_birth": forms.DateInput(attrs={"type": "date"}),
            "joining_date": forms.DateInput(attrs={"type": "date"}),
            "hire_date": forms.DateInput(attrs={"type": "date"}),
            "confirmation_date": forms.DateInput(attrs={"type": "date"}),
            "current_address": forms.Textarea(attrs={"rows": 3}),
            "remarks": forms.Textarea(attrs={"rows": 4}),
            "scheduled_checkin": forms.TextInput(attrs={"placeholder": "HH:MM — e.g. 16:00"}),
            "scheduled_checkout": forms.TextInput(attrs={"placeholder": "HH:MM — e.g. 01:30"}),
            "work_location": forms.TextInput(attrs={
                "list": "workLocationList",
                "placeholder": "e.g. Lahore Office",
                "autocomplete": "off",
            }),
        }

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop("request", None)
        super().__init__(*args, **kwargs)
        self._configure_department_field()
        self._apply_field_content()

        if self.instance.pk and self.instance.user_id:
            if "username" in self.fields:
                self.fields["username"].initial = self.instance.user.username
            if "first_name" in self.fields:
                self.fields["first_name"].initial = self.instance.user.first_name
            if "last_name" in self.fields:
                self.fields["last_name"].initial = self.instance.user.last_name
            if "password" in self.fields:
                self.fields["password"].help_text = (
                    "Leave blank to keep the existing password."
                )
            # Hide setup-email option when editing an existing employee
            if "send_setup_email" in self.fields:
                self.fields["send_setup_email"].widget = forms.HiddenInput()
                self.fields["send_setup_email"].initial = False

        for name in (
            "basic_salary",
            "house_rent_allowance",
            "conveyance_allowance",
            "medical_allowance",
            "other_allowance",
        ):
            if name in self.fields:
                self.fields[name].initial = self.fields[name].initial or 0

        if "role" in self.fields:
            self.fields["role"].help_text = "Role controls the group and admin permissions."

        if "reporting_manager" in self.fields:
            department_value = self._current_department_value()
            if department_value and not self.fields["reporting_manager"].initial:
                manager = self._default_manager_for_department(department_value)
                if manager:
                    self.fields["reporting_manager"].initial = manager

            if self.request:
                self.fields["department"].widget.attrs["data-manager-url"] = reverse(
                    "admin:accounts_employeeprofile_department_default_manager"
                )

    def _configure_department_field(self) -> None:
        if "department" not in self.fields:
            return
        teams = list(
            Team.objects.filter(is_active=True)
            .values_list("name", "department")
            .order_by("name")
        )
        current_department = self._current_department_value()
        choices = []
        team_names = set()
        for team_name, department_name in teams:
            label = (
                f"{team_name} ({department_name})"
                if department_name
                else team_name
            )
            choices.append((team_name, label))
            team_names.add(team_name)

        if current_department and current_department not in team_names:
            choices.append((current_department, current_department))

        self.fields["department"].choices = [("", "— No team assigned —")] + choices
        if current_department:
            self.fields["department"].initial = current_department

    def _current_department_value(self) -> str:
        if self.is_bound:
            return (self.data.get(self.add_prefix("department")) or "").strip()
        if self.instance and self.instance.pk and self.instance.department:
            return self.instance.department.strip()
        return ""

    def _default_manager_for_department(self, department: str):
        if not department:
            return None
        team = (
            Team.objects.filter(is_active=True, name=department)
            .select_related("manager")
            .order_by("name")
            .first()
        )
        if not team:
            # Backward compatibility for any old department-based values already saved.
            team = (
                Team.objects.filter(is_active=True, department=department)
                .select_related("manager")
                .order_by("name")
                .first()
            )
        return team.manager if team else None

    class Media:
        js = ("accounts/js/employee_department_manager.js",)

    def _apply_field_content(self) -> None:
        placeholders = {
            "full_name": "Enter employee full name",
            "username": "Login username",
            "first_name": "Given name",
            "last_name": "Family name",
            "personal_email": "name@gmail.com",
            "official_email": "name@digilatics.com",
            "personal_phone": "+1 555 123 4567",
            "emergency_contact_name": "Primary emergency contact",
            "emergency_contact_number": "+1 555 987 6543",
            "city": "City",
            "country": "Country",
            "current_address": "Current residential address",
            "cnic": "National ID / CNIC",
            "passport_number": "Passport number if available",
            "employee_code": "EMP-1001",
            "department": "Department",
            "designation": "Job title",
            "team": "Team or business unit",
            "work_location": "Office or remote location",
            "shift": "Morning shift",
            "scheduled_checkin": "HH:MM — e.g. 16:00",
            "scheduled_checkout": "HH:MM — e.g. 01:30",
            "basic_salary": "0.00",
            "house_rent_allowance": "0.00",
            "conveyance_allowance": "0.00",
            "medical_allowance": "0.00",
            "other_allowance": "0.00",
            "bank_name": "Bank name",
            "account_title": "Account holder name",
            "account_number": "Account number",
            "iban": "IBAN",
            "remarks": "Internal notes visible to administrators",
            "password": "Set or replace login password",
        }
        help_texts = {
            "official_email": "Used for system access and employee communication.",
            "employee_code": "Keep this unique. It appears across admin lists and records.",
            "joining_date": "Start date visible in onboarding and dashboard widgets.",
            "reporting_manager": "Select the employee's direct line manager.",
            "payment_mode": "Bank mode requires bank name, account title, and account number.",
            "profile_photo": "Square headshots work best in the admin cards and lists.",
            "remarks": "Use for approvals, onboarding notes, or payroll context.",
        }

        for name, placeholder in placeholders.items():
            if name in self.fields:
                self.fields[name].widget.attrs["placeholder"] = placeholder

        for name, text in help_texts.items():
            if name in self.fields:
                self.fields[name].help_text = text

        if "full_name" in self.fields:
            self.fields["full_name"].label = "Employee full name"
        if "cnic" in self.fields:
            self.fields["cnic"].label = "CNIC / National ID"
        if "date_of_birth" in self.fields:
            self.fields["date_of_birth"].label = "Date of birth"
        if "joining_date" in self.fields:
            self.fields["joining_date"].label = "Joining date"
        if "hire_date" in self.fields:
            self.fields["hire_date"].label = "Payroll start date"
            self.fields["hire_date"].required = False
            self.fields["hire_date"].help_text = "Defaults to joining date if left blank."
        if "official_email" in self.fields:
            self.fields["official_email"].label = "Official work email"
        if "personal_phone" in self.fields:
            self.fields["personal_phone"].label = "Personal phone number"
        if "reporting_manager" in self.fields:
            self.fields["reporting_manager"].empty_label = "No manager assigned yet"

    def _parse_time_field(self, field_name: str) -> time_type | None:
        value = self.cleaned_data.get(field_name)
        if not value:
            return None
        if isinstance(value, time_type):
            return value
        raw = str(value).strip()
        for fmt in ("%H:%M:%S", "%H:%M"):
            try:
                from datetime import datetime
                return datetime.strptime(raw, fmt).time()
            except ValueError:
                continue
        raise ValidationError(
            f"Enter a valid time in HH:MM format (e.g. 16:00 or 01:30). Got: '{raw}'"
        )

    def clean_scheduled_checkin(self) -> time_type | None:
        return self._parse_time_field("scheduled_checkin")

    def clean_scheduled_checkout(self) -> time_type | None:
        return self._parse_time_field("scheduled_checkout")

    def clean_username(self) -> str:
        username = self.cleaned_data["username"].strip()
        queryset = User.objects.filter(username__iexact=username)

        if self.instance.pk and self.instance.user_id:
            queryset = queryset.exclude(pk=self.instance.user_id)

        if queryset.exists():
            raise ValidationError("This username is already in use.")

        return username

    def clean_password(self) -> str:
        password = self.cleaned_data.get("password", "")
        username = self.cleaned_data.get("username", "")
        send_setup_email = self.data.get("send_setup_email")

        if not self.instance.pk and not password and not send_setup_email:
            raise ValidationError(
                "Either enter a password or check 'Send password setup email'."
            )

        if password:
            if self.instance.pk and self.instance.user_id:
                user = self.instance.user
            else:
                user = User(username=username)
            password_validation.validate_password(password, user=user)

        return password

    def clean(self):
        cleaned_data = super().clean()
        reporting_manager = cleaned_data.get("reporting_manager")
        payment_mode = cleaned_data.get("payment_mode")
        joining_date = cleaned_data.get("joining_date")
        hire_date = cleaned_data.get("hire_date")
        confirmation_date = cleaned_data.get("confirmation_date")
        personal_email = cleaned_data.get("personal_email")
        official_email = cleaned_data.get("official_email")
        department = cleaned_data.get("department", "").strip()

        if (
            self.instance.pk
            and reporting_manager
            and reporting_manager.pk == self.instance.pk
        ):
            self.add_error("reporting_manager", "An employee cannot report to themselves.")

        if department and not reporting_manager:
            manager = self._default_manager_for_department(department)
            if manager:
                cleaned_data["reporting_manager"] = manager

        if personal_email and official_email and personal_email.lower() == official_email.lower():
            self.add_error(
                "personal_email",
                "Personal and official email addresses should be different.",
            )

        if joining_date and not hire_date:
            cleaned_data["hire_date"] = joining_date

        if joining_date and confirmation_date and confirmation_date < joining_date:
            self.add_error(
                "confirmation_date",
                "Confirmation date cannot be earlier than the joining date.",
            )

        return cleaned_data
