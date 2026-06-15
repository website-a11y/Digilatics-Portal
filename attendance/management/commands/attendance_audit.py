"""
Audit imported attendance to verify completeness and spot problems.

Reports:
  - total records and overall date range
  - records per month (total / present / missing-checkout)
  - employees mapped to the device that have NO records (likely mapping/data gap)
  - employees with records but a high share of single-punch (missing-checkout) days

Read-only — never writes anything.

Usage:
    python manage.py attendance_audit
    python manage.py attendance_audit --from 2026-02-01 --to 2026-06-30
"""
from datetime import date as date_cls

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count, Q
from django.db.models.functions import TruncMonth

from accounts.models import EmployeeProfile
from attendance.models import AttendanceRecord, DeviceEmployee


class Command(BaseCommand):
    help = "Audit imported attendance for completeness"

    def add_arguments(self, parser):
        parser.add_argument("--from", dest="from_date", default=None, help="YYYY-MM-DD")
        parser.add_argument("--to", dest="to_date", default=None, help="YYYY-MM-DD")

    def handle(self, *args, **opts):
        try:
            d_from = date_cls.fromisoformat(opts["from_date"]) if opts["from_date"] else None
            d_to = date_cls.fromisoformat(opts["to_date"]) if opts["to_date"] else None
        except ValueError:
            raise CommandError("Dates must be YYYY-MM-DD")

        qs = AttendanceRecord.objects.all()
        if d_from:
            qs = qs.filter(date__gte=d_from)
        if d_to:
            qs = qs.filter(date__lte=d_to)

        total = qs.count()
        if not total:
            self.stdout.write(self.style.WARNING("No attendance records in this range."))
            return

        first = qs.order_by("date").values_list("date", flat=True).first()
        last = qs.order_by("-date").values_list("date", flat=True).first()
        self.stdout.write(self.style.SUCCESS(f"Total records: {total}"))
        self.stdout.write(f"Date range   : {first} -> {last}\n")

        # ── Per-month breakdown ───────────────────────────────────────────────
        present = AttendanceRecord.StatusChoices.PRESENT
        rows = (
            qs.annotate(m=TruncMonth("date"))
              .values("m")
              .annotate(
                  total=Count("id"),
                  present=Count("id", filter=Q(status=present)),
                  no_out=Count("id", filter=Q(check_in__isnull=False, check_out__isnull=True)),
              )
              .order_by("m")
        )
        self.stdout.write("Month      Total  Present  MissingCheckout")
        self.stdout.write("-------    -----  -------  ---------------")
        for r in rows:
            self.stdout.write(
                f"{r['m'].strftime('%Y-%m')}    {r['total']:5d}  {r['present']:7d}  {r['no_out']:15d}"
            )

        # ── Mapped employees with NO records (mapping or data gap) ─────────────
        mapped_emp_ids = set(DeviceEmployee.objects.values_list("employee_id", flat=True))
        emp_with_records = set(qs.values_list("employee_id", flat=True))
        missing = mapped_emp_ids - emp_with_records
        if missing:
            self.stdout.write(self.style.WARNING(
                f"\n{len(missing)} mapped employee(s) have NO records in this range:"
            ))
            for emp in EmployeeProfile.objects.filter(pk__in=missing).order_by("full_name"):
                dm = DeviceEmployee.objects.filter(employee=emp).first()
                dev = dm.device_user_id if dm else "?"
                self.stdout.write(f"  - {emp.full_name} (device id {dev})")
        else:
            self.stdout.write(self.style.SUCCESS("\nAll mapped employees have at least one record."))

        # ── Per-employee record counts (low counts flag possible gaps) ─────────
        per_emp = (
            qs.values("employee__full_name")
              .annotate(c=Count("id"), no_out=Count("id", filter=Q(check_in__isnull=False, check_out__isnull=True)))
              .order_by("c")
        )
        self.stdout.write("\nPer-employee (lowest counts first):")
        self.stdout.write("Records  MissingOut  Employee")
        for r in per_emp:
            self.stdout.write(
                f"{r['c']:7d}  {r['no_out']:10d}  {r['employee__full_name']}"
            )
