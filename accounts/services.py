from datetime import date

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.db import IntegrityError

from .models import EmployeeProfile


User = get_user_model()


ROLE_PERMISSION_MAP = {
    EmployeeProfile.RoleChoices.EMPLOYEE: [
        "view_employeeprofile",
        "view_leaverequest",
        "add_leaverequest",
        "change_leaverequest",
        "view_leaveallocation",
        "view_leavetype",
    ],
    EmployeeProfile.RoleChoices.MANAGER: [
        "view_employeeprofile",
        "change_employeeprofile",
        "can_manage_team",
        "can_view_employee_directory",
        "view_team",
        "add_team",
        "change_team",
        "can_create_team",
        "can_manage_owned_teams",
        "view_teammember",
        "add_teammember",
        "change_teammember",
        "delete_teammember",
        "can_view_team_directory",
        "view_leavetype",
        "view_leaveallocation",
        "view_leaverequest",
        "add_leaverequest",
        "change_leaverequest",
        "delete_leaverequest",
        "view_leaveallocation",
        "view_leavetype",
        "view_attendancerecord",
    ],
    EmployeeProfile.RoleChoices.APPROVER: [
        "view_employeeprofile",
        "can_approve_employee_records",
        "can_view_employee_directory",
        "view_team",
        "view_teammember",
        "can_view_team_directory",
        "view_leavetype",
        "view_leaveallocation",
        "view_leaverequest",
        "change_leaverequest",
    ],
    EmployeeProfile.RoleChoices.SUPER_ADMIN: None,
}


def ensure_role_groups() -> None:
    for role, codenames in ROLE_PERMISSION_MAP.items():
        group, _created = Group.objects.get_or_create(name=role)

        if codenames is None:
            group.permissions.set(Permission.objects.all())
            continue

        permissions = Permission.objects.filter(codename__in=codenames)
        group.permissions.set(permissions)


def infer_employee_role(user) -> str:
    if user.is_superuser:
        return EmployeeProfile.RoleChoices.SUPER_ADMIN
    if user.is_staff:
        return EmployeeProfile.RoleChoices.MANAGER
    return EmployeeProfile.RoleChoices.EMPLOYEE


def build_employee_profile_defaults(user) -> dict:
    full_name = " ".join(
        part for part in [user.first_name, user.last_name] if part
    ).strip() or user.username
    official_email = user.email or f"{user.username}@portal.local"

    return {
        "full_name": full_name,
        "official_email": official_email,
        "personal_phone": f"000000{user.pk:04d}",
        "cnic": f"AUTO-{user.pk:08d}",
        "employee_code": f"AUTO-{user.pk:05d}",
        "department": "Unassigned",
        "designation": "Unassigned",
        "employment_type": EmployeeProfile.EmploymentTypeChoices.PERMANENT,
        "employment_status": EmployeeProfile.EmploymentStatusChoices.ACTIVE,
        "joining_date": date.today(),
        "shift": "General",
        "basic_salary": 0,
        "role": infer_employee_role(user),
    }


def ensure_employee_profile_for_user(user) -> EmployeeProfile:
    profile, created = EmployeeProfile.objects.get_or_create(
        user=user,
        defaults=build_employee_profile_defaults(user),
    )

    update_fields = []
    inferred_role = infer_employee_role(user)

    if profile.role != inferred_role:
        profile.role = inferred_role
        update_fields.append("role")

    if not profile.full_name:
        profile.full_name = build_employee_profile_defaults(user)["full_name"]
        update_fields.append("full_name")

    if update_fields:
        profile.save(update_fields=update_fields)

    if created:
        sync_user_role(user, profile.role, profile.employment_status)

    return profile


def ensure_employee_profiles_for_existing_users() -> None:
    for user in User.objects.all():
        try:
            ensure_employee_profile_for_user(user)
        except IntegrityError:
            pass


def sync_user_role(user, role: str, employment_status: str) -> None:
    ensure_role_groups()

    user.groups.clear()
    user.groups.add(Group.objects.get(name=role))
    user.is_staff = role in {
        EmployeeProfile.RoleChoices.MANAGER,
        EmployeeProfile.RoleChoices.APPROVER,
        EmployeeProfile.RoleChoices.SUPER_ADMIN,
    }
    user.is_superuser = role == EmployeeProfile.RoleChoices.SUPER_ADMIN
    user.is_active = employment_status != EmployeeProfile.EmploymentStatusChoices.INACTIVE
    user.save(update_fields=["is_staff", "is_superuser", "is_active"])
