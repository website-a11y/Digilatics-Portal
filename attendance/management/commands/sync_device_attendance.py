"""
Management command: pull attendance logs from the ZKTeco SenseFace M2F-LR
device and sync them into AttendanceRecord.

Usage:
    python manage.py sync_device_attendance
    python manage.py sync_device_attendance --host 192.168.1.100
    python manage.py sync_device_attendance --date 2026-04-16
    python manage.py sync_device_attendance --clear-logs
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from attendance.models import AttendanceRecord, DeviceEmployee
from attendance.services import compute_attendance_flags


class Command(BaseCommand):
    help = "Sync attendance logs from the ZKTeco biometric device"

    def add_arguments(self, parser):
        parser.add_argument(
            "--host",
            type=str,
            help="Device IP address (overrides ZK_DEVICE setting)",
        )
        parser.add_argument(
            "--port",
            type=int,
            help="Device port (default: 4370)",
        )
        parser.add_argument(
            "--date",
            dest="filter_date",
            type=str,
            help="Only sync records for this date (YYYY-MM-DD). Omit to sync all.",
        )
        parser.add_argument(
            "--clear-logs",
            action="store_true",
            help="Clear all attendance logs from the device after a successful sync.",
        )

    def handle(self, *args, **options):
        try:
            from zk import ZK
        except ImportError:
            raise CommandError(
                "pyzk is not installed. Run: pip install pyzk"
            )

        device_cfg = getattr(settings, "ZK_DEVICE", {})
        host = options["host"] or device_cfg.get("host")
        port = options["port"] or device_cfg.get("port", 4370)

        if not host:
            raise CommandError(
                "No device host configured. Set ZK_DEVICE['host'] in settings.py "
                "or pass --host <ip>."
            )

        filter_date: date | None = None
        if options["filter_date"]:
            try:
                filter_date = datetime.strptime(options["filter_date"], "%Y-%m-%d").date()
            except ValueError:
                raise CommandError("--date must be in YYYY-MM-DD format.")

        self.stdout.write(f"Connecting to device at {host}:{port} …")

        zk = ZK(
            host,
            port=port,
            timeout=device_cfg.get("timeout", 10),
            password=device_cfg.get("password", 0),
            force_udp=device_cfg.get("force_udp", False),
            ommit_ping=device_cfg.get("ommit_ping", False),
        )

        conn = None
        try:
            conn = zk.connect()
            conn.disable_device()

            self.stdout.write("Connected. Fetching attendance logs …")
            raw_logs = conn.get_attendance()
            self.stdout.write(f"  {len(raw_logs)} log entries retrieved.")

            if options["clear_logs"]:
                conn.clear_attendance()
                self.stdout.write(self.style.WARNING("  Device logs cleared."))

        except Exception as exc:
            raise CommandError(f"Device communication error: {exc}") from exc
        finally:
            if conn:
                try:
                    conn.enable_device()
                    conn.disconnect()
                except Exception:
                    pass

        device_tz_name = device_cfg.get("device_timezone", "UTC")
        self._process_logs(raw_logs, filter_date, device_tz_name)

    def _process_logs(self, raw_logs, filter_date: date | None, device_tz_name: str = "UTC"):
        try:
            device_tz = ZoneInfo(device_tz_name)
        except (ZoneInfoNotFoundError, KeyError):
            self.stdout.write(self.style.WARNING(
                f"Unknown device_timezone '{device_tz_name}', defaulting to UTC"
            ))
            device_tz = ZoneInfo("UTC")

        # Build lookup: device_user_id → EmployeeProfile
        mappings = {
            dm.device_user_id: dm.employee
            for dm in DeviceEmployee.objects.select_related("employee").all()
        }

        if not mappings:
            self.stdout.write(self.style.WARNING(
                "No Device Employee Mappings found. "
                "Add them in Admin → Attendance → Device Employee Mappings."
            ))
            return

        # Group punches: {(employee, date): [datetime, ...]}
        punches: dict[tuple, list[datetime]] = defaultdict(list)

        skipped_unknown = 0
        for log in raw_logs:
            # pyzk log attributes: user_id (str/int), timestamp (datetime)
            try:
                device_uid = int(log.user_id)
            except (ValueError, TypeError):
                skipped_unknown += 1
                continue

            employee = mappings.get(device_uid)
            if employee is None:
                skipped_unknown += 1
                continue

            ts: datetime = log.timestamp
            if not isinstance(ts, datetime):
                continue

            # pyzk returns naive datetimes in the device's local clock timezone.
            # Localise to device_tz, then convert to the portal's local time (EST).
            ts_device = ts.replace(tzinfo=None).replace(tzinfo=device_tz)
            ts_local = timezone.localtime(ts_device)
            # Use the device-local (PKT) calendar date so records land on the
            # correct workday.  Bucketing by EST date shifts morning PKT punches
            # to the previous calendar day due to the 10-hour offset.
            punch_date = ts_device.date()

            if filter_date and punch_date != filter_date:
                continue

            punches[(employee.pk, punch_date)].append(ts_local)

        if skipped_unknown:
            self.stdout.write(self.style.WARNING(
                f"  {skipped_unknown} log entries skipped (no device mapping found)."
            ))

        # Build employee pk → EmployeeProfile cache
        employee_cache = {dm.device_user_id: dm.employee for dm in
                          DeviceEmployee.objects.select_related("employee").all()}
        emp_by_pk = {e.pk: e for e in
                     (dm.employee for dm in DeviceEmployee.objects.select_related("employee").all())}

        created = updated = skipped = 0

        for (emp_pk, punch_date), timestamps in punches.items():
            employee = emp_by_pk.get(emp_pk)
            if not employee:
                continue

            timestamps.sort()
            # .replace(tzinfo=None) strips the tz-awareness to get a naive time
            # suitable for storing in a naive TimeField.
            check_in = timestamps[0].time().replace(tzinfo=None)
            check_out = timestamps[-1].time().replace(tzinfo=None) if len(timestamps) > 1 else None

            # Don't overwrite leave-linked or public holiday records
            existing = AttendanceRecord.objects.filter(
                employee=employee, date=punch_date
            ).first()

            flags = compute_attendance_flags(employee, check_in, check_out)

            if existing:
                if existing.leave_request_id:
                    skipped += 1
                    continue
                if existing.status == AttendanceRecord.StatusChoices.PUBLIC_HOLIDAY:
                    skipped += 1
                    continue
                existing.status = AttendanceRecord.StatusChoices.PRESENT
                existing.check_in = check_in
                if check_out:
                    existing.check_out = check_out
                existing.is_late = flags["is_late"]
                existing.is_early_checkout = flags["is_early_checkout"]
                existing.notes = f"Synced from device ({len(timestamps)} punch(es))"
                existing.save(update_fields=[
                    "status", "check_in", "check_out",
                    "is_late", "is_early_checkout", "notes", "updated_at",
                ])
                updated += 1
            else:
                AttendanceRecord.objects.create(
                    employee=employee,
                    date=punch_date,
                    status=AttendanceRecord.StatusChoices.PRESENT,
                    check_in=check_in,
                    check_out=check_out,
                    is_late=flags["is_late"],
                    is_early_checkout=flags["is_early_checkout"],
                    notes=f"Synced from device ({len(timestamps)} punch(es))",
                )
                created += 1

        self.stdout.write(self.style.SUCCESS(
            f"\nSync complete — {created} created, {updated} updated, {skipped} skipped."
        ))
