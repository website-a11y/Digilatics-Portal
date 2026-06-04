from django.contrib.auth.models import Group, User
from django.test import TestCase

from .models import EmployeeProfile
from .services import (
    ensure_employee_profile_for_user,
    ensure_role_groups,
    sync_user_role,
)


class RolePermissionTests(TestCase):
    def setUp(self) -> None:
        ensure_role_groups()

    def test_role_groups_are_created(self) -> None:
        expected_groups = {"Employee", "Manager", "Approver", "Super Admin"}
        self.assertEqual(
            expected_groups,
            set(Group.objects.values_list("name", flat=True)),
        )

    def test_manager_role_grants_staff_access(self) -> None:
        user = User.objects.create_user(username="manager.one", password="secret123")

        sync_user_role(
            user,
            EmployeeProfile.RoleChoices.MANAGER,
            EmployeeProfile.EmploymentStatusChoices.ACTIVE,
        )

        user.refresh_from_db()
        self.assertTrue(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertTrue(user.groups.filter(name="Manager").exists())
        self.assertTrue(
            user.groups.get(name="Manager").permissions.filter(
                codename="can_manage_team"
            ).exists()
        )

    def test_inactive_employee_is_deactivated(self) -> None:
        user = User.objects.create_user(username="employee.one", password="secret123")

        sync_user_role(
            user,
            EmployeeProfile.RoleChoices.EMPLOYEE,
            EmployeeProfile.EmploymentStatusChoices.INACTIVE,
        )

        user.refresh_from_db()
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_active)
        self.assertTrue(user.groups.filter(name="Employee").exists())

    def test_user_gets_employee_profile_created(self) -> None:
        user = User.objects.create_user(username="portal.user", password="secret123")

        profile = ensure_employee_profile_for_user(user)

        self.assertEqual(profile.user, user)
        self.assertEqual(profile.employee_code, f"AUTO-{user.pk:05d}")
        self.assertEqual(profile.role, EmployeeProfile.RoleChoices.EMPLOYEE)
