from decimal import Decimal, ROUND_HALF_UP

from accounts.models import EmployeeProfile
from teams.models import Team, TeamMember

from .models import LeaveAllocation, LeaveType


def prorated_leave_days(total_days: Decimal, joining_date, year: int) -> Decimal:
    total_days = Decimal(total_days or 0)
    if not joining_date:
        return total_days

    if joining_date.year > year:
        return Decimal("0.00")

    if joining_date.year < year:
        return total_days.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    remaining_months = Decimal(13 - joining_date.month)
    prorated = (total_days * remaining_months) / Decimal("12")
    return prorated.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def eligible_leave_types_for_employee(employee: EmployeeProfile):
    queryset = LeaveType.objects.filter(is_active=True)
    if employee.employment_type == EmployeeProfile.EmploymentTypeChoices.PERMANENT:
        return queryset.filter(is_paid=True)
    if employee.employment_type == EmployeeProfile.EmploymentTypeChoices.PROBATION:
        return queryset.filter(available_for_probation=True)
    return queryset.none()


def ensure_default_leave_allocations_for_employee(
    employee: EmployeeProfile,
    year: int | None = None,
) -> None:
    if employee.employment_status == EmployeeProfile.EmploymentStatusChoices.INACTIVE:
        return

    if year is None:
        year = employee.joining_date.year if employee.joining_date else None
    if year is None:
        return

    eligible_types = eligible_leave_types_for_employee(employee)
    eligible_ids = list(eligible_types.values_list("id", flat=True))

    LeaveAllocation.objects.filter(
        employee=employee,
        year=year,
        notes="Auto-assigned based on employment type and joining date.",
    ).exclude(
        leave_type_id__in=eligible_ids,
    ).delete()

    for leave_type in eligible_types:
        allocated_days = prorated_leave_days(
            leave_type.default_days,
            employee.joining_date,
            year,
        )
        LeaveAllocation.objects.get_or_create(
            employee=employee,
            leave_type=leave_type,
            year=year,
            defaults={
                "allocated_days": allocated_days,
                "carry_forward_days": Decimal("0.00"),
                "notes": "Auto-assigned based on employment type and joining date.",
            },
        )


def bulk_assign_leave_to_employees(
    *,
    leave_type: LeaveType,
    year: int,
    allocated_days: Decimal,
    carry_forward_days: Decimal,
    notes: str = "",
    employees=None,
) -> int:
    if employees is None:
        employees = EmployeeProfile.objects.exclude(
            employment_status=EmployeeProfile.EmploymentStatusChoices.INACTIVE
        )

    count = 0
    for employee in employees:
        final_days = prorated_leave_days(allocated_days, employee.joining_date, year)
        LeaveAllocation.objects.update_or_create(
            employee=employee,
            leave_type=leave_type,
            year=year,
            defaults={
                "allocated_days": final_days,
                "carry_forward_days": carry_forward_days,
                "notes": notes,
            },
        )
        count += 1
    return count


def employees_for_team(team: Team):
    member_ids = TeamMember.objects.filter(team=team).values_list("employee_id", flat=True)
    return EmployeeProfile.objects.filter(
        pk__in=member_ids,
    ).exclude(
        employment_status=EmployeeProfile.EmploymentStatusChoices.INACTIVE
    )
