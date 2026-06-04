from django import forms
from django.core.exceptions import ValidationError

from accounts.models import EmployeeProfile

from .models import Team, TeamMember


class TeamAdminForm(forms.ModelForm):
    class Meta:
        model = Team
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop("request", None)
        super().__init__(*args, **kwargs)
        if "manager" in self.fields:
            self.fields["manager"].queryset = EmployeeProfile.objects.filter(
                role=EmployeeProfile.RoleChoices.MANAGER,
            ).exclude(
                employment_status=EmployeeProfile.EmploymentStatusChoices.INACTIVE
            )
            self.fields["manager"].empty_label = "— Select a manager —"

        if self.request and not self.request.user.is_superuser:
            profile = getattr(self.request.user, "employee_profile", None)
            if (
                profile
                and profile.role == EmployeeProfile.RoleChoices.MANAGER
                and "manager" in self.fields
            ):
                self.fields["manager"].queryset = self.fields["manager"].queryset.filter(
                    pk=profile.pk
                )
                self.fields["manager"].initial = profile

    def clean_manager(self) -> EmployeeProfile:
        manager = self.cleaned_data.get("manager")
        if not manager:
            raise ValidationError("A manager must be selected for the team.")
        if manager.role != EmployeeProfile.RoleChoices.MANAGER:
            raise ValidationError("Selected employee must have Manager role.")
        return manager


class TeamMemberInlineForm(forms.ModelForm):
    class Meta:
        model = TeamMember
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop("request", None)
        super().__init__(*args, **kwargs)
        if "employee" in self.fields:
            self.fields["employee"].queryset = EmployeeProfile.objects.exclude(
                employment_status=EmployeeProfile.EmploymentStatusChoices.INACTIVE
            )

    def clean(self):
        cleaned_data = super().clean()
        team = cleaned_data.get("team") or (self.instance.team if self.instance.team_id else None)
        employee = cleaned_data.get("employee")
        if (
            self.request
            and employee
            and team
            and not self.request.user.is_superuser
        ):
            profile = getattr(self.request.user, "employee_profile", None)
            if profile and profile.role == EmployeeProfile.RoleChoices.MANAGER:
                if team.manager_id != profile.pk:
                    raise ValidationError("Managers can only manage their own teams.")
                if employee.reporting_manager_id != profile.pk:
                    self.add_error(
                        "employee",
                        "Managers can only assign employees they directly supervise.",
                    )
        return cleaned_data
