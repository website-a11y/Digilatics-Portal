"""
Management command to map device user IDs to employees.

Usage:
    python manage.py map_device_employee --code EMP001 --device-id 10039
    python manage.py map_device_employee --name "Basit Ali" --device-id 10039
"""
from django.core.management.base import BaseCommand, CommandError
from accounts.models import EmployeeProfile
from attendance.models import DeviceEmployee


class Command(BaseCommand):
    help = "Map a device user ID to an employee"

    def add_arguments(self, parser):
        parser.add_argument(
            "--code",
            type=str,
            help="Employee code (e.g., EMP001)",
        )
        parser.add_argument(
            "--name",
            type=str,
            help="Employee name (e.g., 'Basit Ali')",
        )
        parser.add_argument(
            "--device-id",
            type=int,
            required=True,
            help="Device user ID (e.g., 10039)",
        )

    def handle(self, *args, **options):
        device_id = options["device_id"]
        emp_code = options["code"]
        emp_name = options["name"]

        if not emp_code and not emp_name:
            raise CommandError(
                "Provide either --code <employee_code> or --name <employee_name>"
            )

        try:
            if emp_code:
                employee = EmployeeProfile.objects.get(employee_code=emp_code)
                self.stdout.write(f"Found employee: {employee.full_name} ({emp_code})")
            else:
                employee = EmployeeProfile.objects.get(full_name__iexact=emp_name)
                self.stdout.write(f"Found employee: {employee.full_name} ({employee.employee_code})")
        except EmployeeProfile.DoesNotExist:
            raise CommandError(
                f"Employee not found. Check the name/code spelling."
            )

        mapping, created = DeviceEmployee.objects.update_or_create(
            employee=employee,
            defaults={"device_user_id": device_id},
        )

        if created:
            self.stdout.write(
                self.style.SUCCESS(
                    f"[OK] Mapped {employee.full_name} -> Device ID {device_id}"
                )
            )
        else:
            self.stdout.write(
                self.style.WARNING(
                    f"[OK] Updated {employee.full_name} -> Device ID {device_id}"
                )
            )
