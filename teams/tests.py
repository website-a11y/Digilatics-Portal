from datetime import date

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase

from accounts.models import EmployeeProfile

from .models import Team, TeamMember


class TeamModelTests(TestCase):
    def setUp(self) -> None:
        self.manager_user = User.objects.create_user(username="manager", password="secret123")
        self.manager = self.manager_user.employee_profile
        self.manager.full_name = "Manager One"
        self.manager.official_email = "manager@company.com"
        self.manager.personal_phone = "123456789"
        self.manager.cnic = "11111-1111111-1"
        self.manager.employee_code = "EMP-001"
        self.manager.department = "Engineering"
        self.manager.designation = "Manager"
        self.manager.employment_type = EmployeeProfile.EmploymentTypeChoices.PERMANENT
        self.manager.employment_status = EmployeeProfile.EmploymentStatusChoices.ACTIVE
        self.manager.joining_date = date(2024, 1, 1)
        self.manager.shift = "Morning"
        self.manager.basic_salary = 1000
        self.manager.role = EmployeeProfile.RoleChoices.MANAGER
        self.manager.save()
        self.employee_user = User.objects.create_user(username="employee", password="secret123")
        self.employee = self.employee_user.employee_profile
        self.employee.full_name = "Employee One"
        self.employee.official_email = "employee@company.com"
        self.employee.personal_phone = "123456780"
        self.employee.cnic = "11111-1111111-2"
        self.employee.employee_code = "EMP-002"
        self.employee.department = "Engineering"
        self.employee.designation = "Engineer"
        self.employee.employment_type = EmployeeProfile.EmploymentTypeChoices.PERMANENT
        self.employee.employment_status = EmployeeProfile.EmploymentStatusChoices.ACTIVE
        self.employee.joining_date = date(2024, 1, 1)
        self.employee.shift = "Morning"
        self.employee.basic_salary = 900
        self.employee.role = EmployeeProfile.RoleChoices.EMPLOYEE
        self.employee.reporting_manager = self.manager
        self.employee.save()
        self.team = Team.objects.create(
            name="Platform",
            code="TEAM-PLATFORM",
            manager=self.manager,
        )

    def test_team_member_prevents_duplicate_primary_team(self):
        TeamMember.objects.create(
            team=self.team,
            employee=self.employee,
            role_in_team=TeamMember.TeamRoleChoices.MEMBER,
            joined_at=date.today(),
            is_primary=True,
        )
        other_team = Team.objects.create(
            name="Ops",
            code="TEAM-OPS",
            manager=self.manager,
        )
        membership = TeamMember(
            team=other_team,
            employee=self.employee,
            role_in_team=TeamMember.TeamRoleChoices.MEMBER,
            joined_at=date.today(),
            is_primary=True,
        )
        with self.assertRaises(ValidationError):
            membership.full_clean()

    def test_team_lead_is_unique_per_team(self):
        TeamMember.objects.create(
            team=self.team,
            employee=self.employee,
            role_in_team=TeamMember.TeamRoleChoices.LEAD,
            joined_at=date.today(),
        )
        second_user = User.objects.create_user(username="employee2", password="secret123")
        second_employee = second_user.employee_profile
        second_employee.full_name = "Employee Two"
        second_employee.official_email = "employee2@company.com"
        second_employee.personal_phone = "123456781"
        second_employee.cnic = "11111-1111111-3"
        second_employee.employee_code = "EMP-003"
        second_employee.department = "Engineering"
        second_employee.designation = "Engineer"
        second_employee.employment_type = EmployeeProfile.EmploymentTypeChoices.PERMANENT
        second_employee.employment_status = EmployeeProfile.EmploymentStatusChoices.ACTIVE
        second_employee.joining_date = date(2024, 1, 1)
        second_employee.shift = "Morning"
        second_employee.basic_salary = 800
        second_employee.role = EmployeeProfile.RoleChoices.EMPLOYEE
        second_employee.reporting_manager = self.manager
        second_employee.save()
        membership = TeamMember(
            team=self.team,
            employee=second_employee,
            role_in_team=TeamMember.TeamRoleChoices.LEAD,
            joined_at=date.today(),
        )
        with self.assertRaises(ValidationError):
            membership.full_clean()

    def test_employee_must_report_to_team_manager(self):
        other_manager_user = User.objects.create_user(username="manager2", password="secret123")
        other_manager = other_manager_user.employee_profile
        other_manager.full_name = "Manager Two"
        other_manager.official_email = "manager2@company.com"
        other_manager.personal_phone = "123456782"
        other_manager.cnic = "11111-1111111-4"
        other_manager.employee_code = "EMP-004"
        other_manager.department = "Engineering"
        other_manager.designation = "Manager"
        other_manager.employment_type = EmployeeProfile.EmploymentTypeChoices.PERMANENT
        other_manager.employment_status = EmployeeProfile.EmploymentStatusChoices.ACTIVE
        other_manager.joining_date = date(2024, 1, 1)
        other_manager.shift = "Morning"
        other_manager.basic_salary = 1100
        other_manager.role = EmployeeProfile.RoleChoices.MANAGER
        other_manager.save()
        foreign_team = Team.objects.create(
            name="Security",
            code="TEAM-SEC",
            manager=other_manager,
        )
        membership = TeamMember(
            team=foreign_team,
            employee=self.employee,
            joined_at=date.today(),
        )
        with self.assertRaises(ValidationError):
            membership.full_clean()
