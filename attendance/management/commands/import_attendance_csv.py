"""
Import attendance records from a CSV exported by zk_export.py.

CSV columns required: user_id, timestamp  (status and punch are optional).
Timestamps are treated as UTC (the device sends UTC) and converted to EST
for storage, matching the live ADMS pipeline.

Usage:
    python manage.py import_attendance_csv attendance_export.csv --dry-run
    python manage.py import_attendance_csv attendance_export.csv
    python manage.py import_attendance_csv attendance_export.csv --from 2026-02-01 --to 2026-05-31
"""
import csv
from collections import defaultdict
from datetime import date as date_cls, datetime
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from attendance.models import AttendanceRecord, DeviceEmployee
from attendance.services import compute_attendance_flags



class Command(BaseCommand):
    help = "Import attendance from a CSV file exported by zk_export.py"

    def add_arguments(self, parser):
        parser.add_argument("csv_file", help="Path to the CSV file")
        parser.add_argument(
            "--from", dest="from_date", default=None,
            help="Only import punches on/after this date YYYY-MM-DD",
        )
        parser.add_argument(
            "--to", dest="to_date", default=None,
            help="Only import punches on/before this date YYYY-MM-DD",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Parse and report counts without writing any records",
        )

    def handle(self, *args, **opts):
        csv_path = opts["csv_file"]
        dry = opts["dry_run"]

        try:
            d_from = date_cls.fromisoformat(opts["from_date"]) if opts["from_date"] else None
            d_to = date_cls.fromisoformat(opts["to_date"]) if opts["to_date"] else None
        except ValueError:
            raise CommandError("Dates must be YYYY-MM-DD")

        if dry:
            self.stdout.write(self.style.WARNING("DRY RUN — no records will be written\n"))

        ignored = {int(x) for x in getattr(settings, "ZK_IGNORED_DEVICE_IDS", [])}
        mappings = {
            dm.device_user_id: dm.employee
            for dm in DeviceEmployee.objects.select_related("employee")
        }

        unknown = set()
        punches = defaultdict(list)  # (emp_pk, est_date) -> [(time, status_code)]
        total_rows = 0
        skipped_ignored = 0
        skipped_range = 0

        try:
            fh = open(csv_path, "r", encoding="utf-8", errors="replace", newline="")
        except OSError as exc:
            raise CommandError(f"Cannot open CSV: {exc}")

        with fh:
            reader = csv.DictReader(fh)
            for row in reader:
                total_rows += 1
                try:
                    device_uid = int(row["user_id"])
                except (KeyError, ValueError):
                    continue

                if device_uid in ignored:
                    skipped_ignored += 1
                    continue

                try:
                    punch_naive = datetime.strptime(row["timestamp"].strip(), "%Y-%m-%d %H:%M:%S")
                except (KeyError, ValueError):
                    continue

                if d_from and punch_naive.date() < d_from:
                    skipped_range += 1
                    continue
                if d_to and punch_naive.date() > d_to:
                    skipped_range += 1
                    continue

                employee = mappings.get(device_uid)
                if employee is None:
                    unknown.add(device_uid)
                    continue

                # Device sends timestamps in its own clock timezone (PKT = UTC+5).
                _device_tz = ZoneInfo(settings.ZK_DEVICE.get("device_timezone", "UTC"))
                punch_local = timezone.localtime(
                    timezone.make_aware(punch_naive, _device_tz)
                )

                try:
                    status_code = int(row.get("status") or 0)
                except (ValueError, TypeError):
                    status_code = 0

                punches[(employee.pk, punch_local.date())].append(
                    (punch_local.time(), status_code)
                )

        self.stdout.write(f"Total CSV rows       : {total_rows}")
        self.stdout.write(f"Skipped (ignored IDs): {skipped_ignored}")
        self.stdout.write(f"Skipped (out of range): {skipped_range}")
        self.stdout.write(f"(employee, day) groups: {len(punches)}")
        if unknown:
            self.stdout.write(self.style.WARNING(
                f"Unmapped device IDs (no employee linked): {sorted(unknown)}"
            ))

        emp_by_pk = {e.pk: e for e in mappings.values()}
        created = updated = skipped = 0

        for (emp_pk, punch_date), plist in sorted(punches.items()):
            employee = emp_by_pk.get(emp_pk)
            if not employee:
                continue
            plist.sort(key=lambda x: x[0])
            times = [t for t, _ in plist]
            check_in = times[0]
            check_out = times[-1] if len(times) > 1 else None
            flags = compute_attendance_flags(employee, check_in, check_out)
            note = f"Synced from device ({len(plist)} punch(es))"

            existing = AttendanceRecord.objects.filter(
                employee=employee, date=punch_date
            ).first()

            if existing:
                if (
                    existing.leave_request_id
                    or existing.status == AttendanceRecord.StatusChoices.PUBLIC_HOLIDAY
                ):
                    skipped += 1
                    continue
                updated += 1
                if not dry:
                    existing.status = AttendanceRecord.StatusChoices.PRESENT
                    existing.check_in = check_in
                    if check_out:
                        existing.check_out = check_out
                    existing.is_late = flags["is_late"]
                    existing.is_early_checkout = flags["is_early_checkout"]
                    existing.notes = note
                    existing.save(update_fields=[
                        "status", "check_in", "check_out",
                        "is_late", "is_early_checkout", "notes", "updated_at",
                    ])
            else:
                created += 1
                if not dry:
                    AttendanceRecord.objects.create(
                        employee=employee,
                        date=punch_date,
                        status=AttendanceRecord.StatusChoices.PRESENT,
                        check_in=check_in,
                        check_out=check_out,
                        is_late=flags["is_late"],
                        is_early_checkout=flags["is_early_checkout"],
                        notes=note,
                    )

        prefix = "DRY RUN — would " if dry else ""
        self.stdout.write(self.style.SUCCESS(
            f"\n{prefix}created={created}  updated={updated}  skipped={skipped}"
        ))
        if dry:
            self.stdout.write("Re-run without --dry-run to apply.")
