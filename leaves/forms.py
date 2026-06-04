from django import forms
from django.utils import timezone

from accounts.models import EmployeeProfile
from teams.models import Team

from .models import LeaveAllocation, LeaveRequest, LeaveType
from .services import bulk_assign_leave_to_employees, employees_for_team


class LeaveAllocationAdminForm(forms.ModelForm):
    class Meta:
        model = LeaveAllocation
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["employee"].queryset = EmployeeProfile.objects.exclude(
            employment_status=EmployeeProfile.EmploymentStatusChoices.INACTIVE
        )
        self.fields["year"].initial = self.fields["year"].initial or timezone.now().year


class LeaveRequestAdminForm(forms.ModelForm):
    class Meta:
        model = LeaveRequest
        fields = "__all__"
        widgets = {
            "from_date": forms.DateInput(attrs={"type": "date"}),
            "to_date": forms.DateInput(attrs={"type": "date"}),
            "reason": forms.Textarea(attrs={"rows": 4}),
            "remarks": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop("request", None)
        super().__init__(*args, **kwargs)
        self.fields["employee"].queryset = EmployeeProfile.objects.exclude(
            employment_status=EmployeeProfile.EmploymentStatusChoices.INACTIVE
        )
        self.fields["leave_type"].queryset = LeaveType.objects.filter(is_active=True)

        if self.request and not self.request.user.is_superuser:
            profile = getattr(self.request.user, "employee_profile", None)
            if profile:
                self.fields["employee"].queryset = self.fields["employee"].queryset.filter(pk=profile.pk)
                self.fields["employee"].initial = profile

    def clean(self):
        cleaned_data = super().clean()
        from_date = cleaned_data.get("from_date")
        to_date = cleaned_data.get("to_date")
        number_of_days = cleaned_data.get("number_of_days")
        if from_date and to_date and (not number_of_days or number_of_days <= 0):
            cleaned_data["number_of_days"] = (to_date - from_date).days + 1
        return cleaned_data


class BulkAllocationForm(forms.Form):
    leave_type = forms.ModelChoiceField(queryset=LeaveType.objects.filter(is_active=True))
    year = forms.IntegerField(initial=timezone.now().year, min_value=2000)
    allocated_days = forms.DecimalField(max_digits=6, decimal_places=2, min_value=0)
    carry_forward_days = forms.DecimalField(max_digits=6, decimal_places=2, min_value=0, initial=0)
    team = forms.ModelChoiceField(
        queryset=Team.objects.filter(is_active=True),
        required=False,
        help_text="Leave blank to assign to all active employees.",
    )
    notes = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}))

    def save(self) -> int:
        data = self.cleaned_data
        employees = (
            employees_for_team(data["team"])
            if data.get("team")
            else EmployeeProfile.objects.exclude(
                employment_status=EmployeeProfile.EmploymentStatusChoices.INACTIVE
            )
        )
        return bulk_assign_leave_to_employees(
            leave_type=data["leave_type"],
            year=data["year"],
            allocated_days=data["allocated_days"],
            carry_forward_days=data["carry_forward_days"],
            notes=data["notes"],
            employees=employees,
        )
