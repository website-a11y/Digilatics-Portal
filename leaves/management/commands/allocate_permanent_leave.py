from datetime import date

from django.core.management.base import BaseCommand

from accounts.models import EmployeeProfile

from leaves.models import LeaveType
from leaves.services import bulk_assign_leave_to_employees


class Command(BaseCommand):
    help = (
        "Allocate default leave allocations for all active permanent employees "
        "according to the configured leave type defaults."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--year",
            type=int,
            default=date.today().year,
            help="Year for which leave allocations should be assigned.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Recreate allocations for the given year by overwriting existing ones.",
        )

    def handle(self, *args, **options):
        year = options["year"]
        force = options["force"]

        employees = EmployeeProfile.objects.filter(
            employment_type=EmployeeProfile.EmploymentTypeChoices.PERMANENT,
        ).exclude(
            employment_status=EmployeeProfile.EmploymentStatusChoices.INACTIVE,
        )

        leave_types = LeaveType.objects.filter(
            is_active=True,
            is_paid=True,
        )

        if not leave_types.exists():
            self.stdout.write(self.style.WARNING("No eligible paid leave types found for permanent employees."))
            return

        if force:
            from leaves.models import LeaveAllocation

            LeaveAllocation.objects.filter(year=year, employee__in=employees, leave_type__in=leave_types).delete()
            self.stdout.write(self.style.NOTICE("Existing allocations deleted for the selected year."))

        total_assigned = 0
        for leave_type in leave_types:
            assigned = bulk_assign_leave_to_employees(
                leave_type=leave_type,
                year=year,
                allocated_days=leave_type.default_days,
                carry_forward_days=0,
                notes="Auto-assigned for permanent employees.",
                employees=employees,
            )
            total_assigned += assigned
            self.stdout.write(
                self.style.SUCCESS(
                    f"Assigned {leave_type.default_days} days of '{leave_type.name}' to {assigned} permanent employees."
                )
            )

        self.stdout.write(self.style.SUCCESS(
            f"Completed leave allocation for {total_assigned} employee-leave combinations in {year}."
        ))
