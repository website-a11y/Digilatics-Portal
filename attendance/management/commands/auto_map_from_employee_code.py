"""
Management command: auto_map_from_employee_code

For every EmployeeProfile whose employee_code is a pure integer,
create (or update) a DeviceEmployee mapping using that integer as
the device_user_id.

Usage:
    python manage.py auto_map_from_employee_code
    python manage.py auto_map_from_employee_code --dry-run
"""
from django.core.management.base import BaseCommand

from accounts.models import EmployeeProfile
from attendance.models import DeviceEmployee


class Command(BaseCommand):
    help = "Auto-map all employees to device IDs using their numeric employee code."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be mapped without saving.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN — no changes will be saved.\n"))

        created = updated = skipped = 0

        for emp in EmployeeProfile.objects.all().order_by("employee_code"):
            code = (emp.employee_code or "").strip()
            if not code.isdigit():
                self.stdout.write(
                    f"  SKIP  {emp.full_name!r} — code {code!r} is not numeric"
                )
                skipped += 1
                continue

            device_id = int(code)

            if dry_run:
                existing = DeviceEmployee.objects.filter(employee=emp).first()
                if existing:
                    self.stdout.write(
                        f"  UPDATE {emp.full_name!r}  {existing.device_user_id} → {device_id}"
                    )
                    updated += 1
                else:
                    self.stdout.write(
                        f"  CREATE {emp.full_name!r}  → device ID {device_id}"
                    )
                    created += 1
                continue

            mapping, was_created = DeviceEmployee.objects.update_or_create(
                employee=emp,
                defaults={"device_user_id": device_id},
            )
            if was_created:
                created += 1
            else:
                updated += 1

        self.stdout.write("")
        if dry_run:
            self.stdout.write(self.style.WARNING(
                f"DRY RUN complete.\n"
                f"  Would create : {created}\n"
                f"  Would update : {updated}\n"
                f"  Skipped      : {skipped} (non-numeric codes)\n"
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                f"Done.\n"
                f"  Created  : {created}\n"
                f"  Updated  : {updated}\n"
                f"  Skipped  : {skipped} (non-numeric codes)\n"
            ))
