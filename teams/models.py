from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from accounts.models import EmployeeProfile


class Team(models.Model):
    name = models.CharField(max_length=120, unique=True)
    code = models.CharField(max_length=30, unique=True)
    department = models.CharField(max_length=120, blank=True)
    description = models.TextField(blank=True)
    manager = models.ForeignKey(
        EmployeeProfile,
        on_delete=models.PROTECT,
        related_name="managed_teams",
    )
    parent_team = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="sub_teams",
    )
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="created_teams",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        permissions = [
            ("can_create_team", "Can create teams"),
            ("can_manage_owned_teams", "Can manage owned teams"),
            ("can_view_team_directory", "Can view team directory"),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.code})"

    @property
    def member_count(self) -> int:
        return self.members.count()

    def clean(self) -> None:
        if (
            self.parent_team_id
            and self.pk
            and self.parent_team_id == self.pk
        ):
            raise ValidationError({"parent_team": "A team cannot be its own parent."})

        if self.manager and self.manager.role != EmployeeProfile.RoleChoices.MANAGER:
            raise ValidationError({"manager": "Only employees with Manager role can lead a team."})

        if (
            self.manager
            and self.manager.employment_status == EmployeeProfile.EmploymentStatusChoices.INACTIVE
        ):
            raise ValidationError({"manager": "Inactive employees cannot manage teams."})


class TeamMember(models.Model):
    class TeamRoleChoices(models.TextChoices):
        MEMBER = "Member", "Member"
        LEAD = "Lead", "Lead"
        COORDINATOR = "Coordinator", "Coordinator"

    team = models.ForeignKey(
        Team,
        on_delete=models.CASCADE,
        related_name="members",
    )
    employee = models.ForeignKey(
        EmployeeProfile,
        on_delete=models.CASCADE,
        related_name="team_memberships",
    )
    role_in_team = models.CharField(
        max_length=20,
        choices=TeamRoleChoices.choices,
        default=TeamRoleChoices.MEMBER,
    )
    joined_at = models.DateField()
    is_primary = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["employee__full_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["team", "employee"],
                name="unique_team_member_assignment",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.employee.full_name} -> {self.team.name}"

    def clean(self) -> None:
        errors = {}

        if (
            self.employee
            and self.employee.employment_status == EmployeeProfile.EmploymentStatusChoices.INACTIVE
        ):
            errors["employee"] = "Inactive employees cannot be added to active teams."

        if (
            self.team
            and self.employee
            and self.team.is_active
            and self.employee.reporting_manager_id
            and self.team.manager_id != self.employee.reporting_manager_id
        ):
            errors["employee"] = (
                "Managers can only assign employees they directly supervise."
            )

        if self.team and self.employee and self.team.manager_id == self.employee_id:
            errors["employee"] = "The team manager is already assigned as team lead."

        if self.is_primary and self.employee_id:
            queryset = TeamMember.objects.filter(
                employee_id=self.employee_id,
                is_primary=True,
            )
            if self.pk:
                queryset = queryset.exclude(pk=self.pk)
            if queryset.exists():
                errors["is_primary"] = "An employee can have only one primary team."

        if self.role_in_team == self.TeamRoleChoices.LEAD and self.team_id:
            queryset = TeamMember.objects.filter(
                team_id=self.team_id,
                role_in_team=self.TeamRoleChoices.LEAD,
            )
            if self.pk:
                queryset = queryset.exclude(pk=self.pk)
            if queryset.exists():
                errors["role_in_team"] = "A team can have only one lead member."

        if errors:
            raise ValidationError(errors)
