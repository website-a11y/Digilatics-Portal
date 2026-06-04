from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase

from accounts.models import EmployeeProfile
from teams.models import Team, TeamMember

from .models import LeaveAllocation, LeaveRequest, LeaveType
from .services import (
    bulk_assign_leave_to_employees,
    employees_for_team,
    ensure_default_leave_allocations_for_employee,
    prorated_leave_days,
)


class LeaveModelTests(TestCase):
    def setUp(self) -> None:
        self.manager_user = User.objects.create_user(username="leave.manager", password="secret123")
        self.manager = self.manager_user.employee_profile
        self.manager.full_name = "Leave Manager"
        self.manager.employee_code = "MGR-001"
        self.manager.cnic = "CNIC-MGR-001"
        self.manager.official_email = "manager@leave.com"
        self.manager.personal_phone = "123456789"
        self.manager.department = "HR"
        self.manager.designation = "Manager"
        self.manager.shift = "Morning"
        self.manager.basic_salary = 1000
        self.manager.role = EmployeeProfile.RoleChoices.MANAGER
        self.manager.save()

        self.employee_user = User.objects.create_user(username="leave.employee", password="secret123")
        self.employee = self.employee_user.employee_profile
        self.employee.full_name = "Leave Employee"
        self.employee.employee_code = "EMP-LEAVE-1"
        self.employee.cnic = "CNIC-EMP-001"
        self.employee.official_email = "employee@leave.com"
        self.employee.personal_phone = "987654321"
        self.employee.department = "Operations"
        self.employee.designation = "Officer"
        self.employee.shift = "Morning"
        self.employee.basic_salary = 800
        self.employee.reporting_manager = self.manager
        self.employee.save()

        self.leave_type = LeaveType.objects.create(
            name="Annual Leave",
            is_paid=True,
            default_days=Decimal("14.00"),
        )
        self.wfh_type = LeaveType.objects.create(
            name="Work From Home",
            is_paid=False,
            default_days=Decimal("12.00"),
            available_for_probation=True,
        )
        self.allocation = LeaveAllocation.objects.create(
            employee=self.employee,
            leave_type=self.leave_type,
            year=2026,
            allocated_days=Decimal("14.00"),
            carry_forward_days=Decimal("2.00"),
        )

    def test_leave_request_uses_available_balance(self):
        request = LeaveRequest(
            employee=self.employee,
            leave_type=self.leave_type,
            from_date=date(2026, 4, 10),
            to_date=date(2026, 4, 12),
            number_of_days=Decimal("3.00"),
        )
        request.full_clean()
        request.save()
        self.assertEqual(self.allocation.booked_days, Decimal("3.00"))
        self.assertEqual(self.allocation.remaining_days, Decimal("13.00"))

    def test_leave_request_cannot_exceed_balance(self):
        request = LeaveRequest(
            employee=self.employee,
            leave_type=self.leave_type,
            from_date=date(2026, 4, 10),
            to_date=date(2026, 4, 30),
            number_of_days=Decimal("30.00"),
        )
        with self.assertRaises(ValidationError):
            request.full_clean()

    def test_leave_allocation_blocks_inactive_employee(self):
        self.employee.employment_status = EmployeeProfile.EmploymentStatusChoices.INACTIVE
        self.employee.save(update_fields=["employment_status"])
        allocation = LeaveAllocation(
            employee=self.employee,
            leave_type=self.leave_type,
            year=2026,
            allocated_days=Decimal("5.00"),
        )
        with self.assertRaises(ValidationError):
            allocation.full_clean()

    def test_prorated_leave_days_for_mid_year_joining(self):
        self.assertEqual(
            prorated_leave_days(Decimal("12.00"), date(2026, 6, 10), 2026),
            Decimal("7.00"),
        )

    def test_permanent_employee_gets_paid_leave_defaults(self):
        employee_user = User.objects.create_user(username="perm.user", password="secret123")
        employee = employee_user.employee_profile
        employee.full_name = "Permanent User"
        employee.employee_code = "EMP-PERM"
        employee.cnic = "CNIC-PERM-001"
        employee.official_email = "perm@leave.com"
        employee.personal_phone = "1122334455"
        employee.department = "Admin"
        employee.designation = "Assistant"
        employee.shift = "Morning"
        employee.basic_salary = 500
        employee.joining_date = date(2026, 6, 1)
        employee.employment_type = EmployeeProfile.EmploymentTypeChoices.PERMANENT
        employee.save()

        ensure_default_leave_allocations_for_employee(employee, year=2026)

        self.assertTrue(
            LeaveAllocation.objects.filter(employee=employee, leave_type=self.leave_type).exists()
        )
        self.assertFalse(
            LeaveAllocation.objects.filter(employee=employee, leave_type=self.wfh_type).exists()
        )

    def test_probation_employee_gets_only_probation_allowed_leave(self):
        employee_user = User.objects.create_user(username="prob.user", password="secret123")
        employee = employee_user.employee_profile
        employee.full_name = "Probation User"
        employee.employee_code = "EMP-PROB"
        employee.cnic = "CNIC-PROB-001"
        employee.official_email = "prob@leave.com"
        employee.personal_phone = "5544332211"
        employee.department = "Admin"
        employee.designation = "Trainee"
        employee.shift = "Morning"
        employee.basic_salary = 400
        employee.joining_date = date(2026, 6, 1)
        employee.employment_type = EmployeeProfile.EmploymentTypeChoices.PROBATION
        employee.save()

        ensure_default_leave_allocations_for_employee(employee, year=2026)

        self.assertFalse(
            LeaveAllocation.objects.filter(employee=employee, leave_type=self.leave_type).exists()
        )
        self.assertTrue(
            LeaveAllocation.objects.filter(employee=employee, leave_type=self.wfh_type).exists()
        )

    def test_bulk_assign_to_team_only(self):
        team = Team.objects.create(name="Ops", code="OPS", manager=self.manager)
        TeamMember.objects.create(
            team=team,
            employee=self.employee,
            joined_at=date.today(),
        )
        count = bulk_assign_leave_to_employees(
            leave_type=self.leave_type,
            year=2026,
            allocated_days=Decimal("12.00"),
            carry_forward_days=Decimal("0.00"),
            employees=employees_for_team(team),
        )
        self.assertEqual(count, 1)
