from datetime import date, timedelta

from django.core.cache import cache
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class Shift(models.Model):
    name = models.CharField(max_length=120, unique=True)
    start_time = models.TimeField()
    end_time = models.TimeField()
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["start_time", "name"]
        verbose_name = "Shift"
        verbose_name_plural = "Shifts"

    def __str__(self):
        return self.name

    @property
    def working_hours(self):
        from datetime import datetime
        start = datetime.combine(date.today(), self.start_time)
        end = datetime.combine(date.today(), self.end_time)
        if end <= start:
            end += timedelta(days=1)
        return round((end - start).seconds / 3600, 1)

    @property
    def employee_count(self):
        return self.employees.count()


class AttendancePolicy(models.Model):
    """Global attendance policy: buffer times for late check-in and early check-out."""

    checkin_buffer_minutes = models.PositiveIntegerField(
        default=0,
        verbose_name="Check-in Buffer (minutes)",
        help_text=(
            "Grace period after scheduled check-in. "
            "If an employee punches in more than this many minutes late, they are marked as Late."
        ),
    )
    checkout_buffer_minutes = models.PositiveIntegerField(
        default=0,
        verbose_name="Check-out Buffer (minutes)",
        help_text=(
            "Early-leave allowance before scheduled check-out. "
            "If an employee punches out more than this many minutes early, they are marked as Early Checkout."
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Attendance Policy"
        verbose_name_plural = "Attendance Policy"

    def __str__(self):
        return (
            f"Attendance Policy — "
            f"Check-in buffer: {self.checkin_buffer_minutes}m, "
            f"Check-out buffer: {self.checkout_buffer_minutes}m"
        )


class SyncSchedule(models.Model):
    """Configuration for automated attendance sync schedule."""

    sync_time_1 = models.TimeField(
        default="18:30",  # 6:30 PM
        help_text="First sync time (24-hour format)",
    )
    sync_time_2 = models.TimeField(
        default="02:30",  # 2:30 AM
        help_text="Second sync time (24-hour format)",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Sync Schedule"
        verbose_name_plural = "Sync Schedule"

    def __str__(self):
        return f"Sync at {self.sync_time_1.strftime('%H:%M')} and {self.sync_time_2.strftime('%H:%M')}"


class DeviceEmployee(models.Model):
    """Maps a ZKTeco device user ID to an EmployeeProfile."""

    employee = models.OneToOneField(
        "accounts.EmployeeProfile",
        on_delete=models.CASCADE,
        related_name="device_mapping",
    )
    device_user_id = models.PositiveIntegerField(
        unique=True,
        verbose_name="Device User ID",
        help_text="The numeric user ID enrolled on the biometric device (starts from 10000).",
    )

    class Meta:
        verbose_name = "Device Employee Mapping"
        verbose_name_plural = "Device Employee Mappings"
        ordering = ["device_user_id"]

    def __str__(self):
        return f"{self.employee.full_name} → Device ID {self.device_user_id}"


class PublicHoliday(models.Model):
    name = models.CharField(max_length=200)
    start_date = models.DateField()
    end_date = models.DateField(
        null=True, blank=True,
        help_text="Leave blank for a single-day holiday.",
    )
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["start_date"]
        verbose_name = "Public Holiday"
        verbose_name_plural = "Public Holidays"

    def __str__(self):
        end = self.end_date or self.start_date
        if end == self.start_date:
            return f"{self.name} — {self.start_date.strftime('%d %b %Y')}"
        return f"{self.name} — {self.start_date.strftime('%d %b')} to {end.strftime('%d %b %Y')}"

    @property
    def display_date(self):
        end = self.end_date or self.start_date
        if end == self.start_date:
            return self.start_date.strftime("%d %b %Y")
        return f"{self.start_date.strftime('%d %b')} – {end.strftime('%d %b %Y')}"

    @property
    def duration_days(self):
        from datetime import timedelta
        end = self.end_date or self.start_date
        return (end - self.start_date).days + 1

    @classmethod
    def dates_in_range(cls, range_start, range_end) -> set:
        """Return a set of all active holiday dates between range_start and range_end inclusive."""
        from datetime import timedelta
        from django.db.models import Q
        result = set()
        qs = cls.objects.filter(
            is_active=True,
            start_date__lte=range_end,
        ).filter(
            Q(end_date__isnull=True, start_date__gte=range_start) |
            Q(end_date__gte=range_start)
        )
        for h in qs:
            d = h.start_date
            h_end = h.end_date or h.start_date
            while d <= h_end:
                if range_start <= d <= range_end:
                    result.add(d)
                d += timedelta(days=1)
        return result


class CompanyWFHDay(models.Model):
    """
    A company-wide WFH day (or period) declared by HR/Admin.
    All employees are automatically WFH on these dates without using personal WFH balance.
    Exception: employees on approved leave on any of these dates are counted as on leave.
    """

    start_date = models.DateField()
    end_date = models.DateField(
        null=True, blank=True,
        help_text="Leave blank for a single-day WFH declaration.",
    )
    title = models.CharField(max_length=200, default="Company WFH Day")
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    declared_by = models.ForeignKey(
        "auth.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="declared_wfh_days",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-start_date"]
        verbose_name = "Company WFH Day"
        verbose_name_plural = "Company WFH Days"

    def __str__(self):
        end = self.end_date or self.start_date
        if end == self.start_date:
            return f"{self.title} — {self.start_date.strftime('%d %b %Y')}"
        return f"{self.title} — {self.start_date.strftime('%d %b')} to {end.strftime('%d %b %Y')}"

    @property
    def display_date(self):
        end = self.end_date or self.start_date
        if end == self.start_date:
            return self.start_date.strftime("%d %b %Y")
        return f"{self.start_date.strftime('%d %b')} – {end.strftime('%d %b %Y')}"

    @classmethod
    def dates_in_range(cls, range_start, range_end) -> set:
        """Return a set of all active company WFH dates between range_start and range_end."""
        from datetime import timedelta
        from django.db.models import Q
        result = set()
        qs = cls.objects.filter(
            is_active=True,
            start_date__lte=range_end,
        ).filter(
            Q(end_date__isnull=True, start_date__gte=range_start) |
            Q(end_date__gte=range_start)
        )
        for h in qs:
            d = h.start_date
            h_end = h.end_date or h.start_date
            while d <= h_end:
                if range_start <= d <= range_end:
                    result.add(d)
                d += timedelta(days=1)
        return result


class AttendanceRecord(models.Model):
    class StatusChoices(models.TextChoices):
        PRESENT = "present", "Present"
        ABSENT = "absent", "Absent"
        WORK_FROM_HOME = "work_from_home", "Work From Home"
        ON_LEAVE_PAID = "on_leave_paid", "On Leave (Paid)"
        ON_LEAVE_UNPAID = "on_leave_unpaid", "On Leave (Unpaid)"
        ON_HOURLY_LEAVE = "on_hourly_leave", "On Hourly Leave"
        PUBLIC_HOLIDAY = "public_holiday", "Public Holiday"
        HALF_DAY = "half_day", "Half Day"

    employee = models.ForeignKey(
        "accounts.EmployeeProfile",
        on_delete=models.CASCADE,
        related_name="attendance_records",
    )
    # When this record was created by an approved leave request, link it here.
    # SET_NULL so deleting a leave request doesn't wipe attendance history.
    leave_request = models.ForeignKey(
        "leaves.LeaveRequest",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="attendance_records",
        verbose_name="Leave Request",
    )
    date = models.DateField()
    status = models.CharField(
        max_length=20,
        choices=StatusChoices.choices,
        default=StatusChoices.PRESENT,
    )
    check_in = models.TimeField(null=True, blank=True, verbose_name="Check In")
    check_out = models.TimeField(null=True, blank=True, verbose_name="Check Out")
    is_late = models.BooleanField(default=False, verbose_name="Late Arrival")
    is_early_checkout = models.BooleanField(default=False, verbose_name="Early Checkout")
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("employee", "date")
        ordering = ["-date", "employee__full_name"]
        verbose_name = "Attendance Record"
        verbose_name_plural = "Attendance Records"

    def __str__(self):
        return f"{self.employee.full_name} — {self.date} — {self.get_status_display()}"


class DeviceSyncFlag(models.Model):
    """
    Singleton flag requesting a full re-sync of all punches from the device.

    Stored in the database (not a file) because the management command runs as a
    different OS user than the gunicorn web process; a shared flag file kept
    hitting directory/ownership permission problems. The DB is shared cleanly.
    """
    full_sync_from = models.DateField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Device Sync Flag"
        verbose_name_plural = "Device Sync Flags"

    def __str__(self):
        return f"full_sync_from={self.full_sync_from}"

    @classmethod
    def request(cls, from_date):
        """Mark that the device should re-upload all punches from from_date."""
        obj, _ = cls.objects.get_or_create(pk=1)
        obj.full_sync_from = from_date
        obj.save(update_fields=["full_sync_from", "updated_at"])

    @classmethod
    def peek(cls):
        """Return the pending full-sync start date without clearing it."""
        obj = cls.objects.filter(pk=1).first()
        return obj.full_sync_from if obj else None

    @classmethod
    def consume(cls):
        """Return the pending full-sync start date and clear it (one-shot)."""
        obj = cls.objects.filter(pk=1).first()
        if obj and obj.full_sync_from:
            d = obj.full_sync_from
            obj.full_sync_from = None
            obj.save(update_fields=["full_sync_from", "updated_at"])
            return d
        return None


# ── System-wide display settings ──────────────────────────────────────────────

class SystemSetting(models.Model):
    """Singleton model (pk=1) that holds portal-wide display preferences."""

    TIMEZONE_CHOICES = [
        ("America/New_York",    "Eastern Time (ET)  —  UTC-5 / UTC-4"),
        ("America/Chicago",     "Central Time (CT)  —  UTC-6 / UTC-5"),
        ("America/Denver",      "Mountain Time (MT)  —  UTC-7 / UTC-6"),
        ("America/Los_Angeles", "Pacific Time (PT)  —  UTC-8 / UTC-7"),
        ("America/Phoenix",     "Arizona (MST, no DST)  —  UTC-7"),
        ("Asia/Karachi",        "Pakistan Standard Time (PKT)  —  UTC+5"),
        ("Asia/Kolkata",        "India Standard Time (IST)  —  UTC+5:30"),
        ("Asia/Dubai",          "Gulf Standard Time (GST)  —  UTC+4"),
        ("Asia/Riyadh",         "Arabia Standard Time (AST)  —  UTC+3"),
        ("Europe/London",       "Greenwich / British Time (GMT/BST)  —  UTC+0/+1"),
        ("Europe/Paris",        "Central European Time (CET)  —  UTC+1/+2"),
        ("UTC",                 "Coordinated Universal Time (UTC)  —  UTC+0"),
    ]

    _CACHE_KEY = "system_setting_display_tz"

    display_timezone = models.CharField(
        max_length=100,
        choices=TIMEZONE_CHOICES,
        default="America/New_York",
        verbose_name="Display Timezone",
        help_text=(
            "All attendance check-in/out times and leave times across the portal and admin "
            "will be converted and displayed in this timezone. "
            "Device data is stored internally in Eastern Time (ET) and converted on the fly."
        ),
    )

    device_timezone = models.CharField(
        max_length=100,
        choices=TIMEZONE_CHOICES,
        default="Asia/Karachi",
        verbose_name="Device Timezone",
        help_text=(
            "The timezone the biometric device's clock is set to. Incoming punch "
            "timestamps are interpreted in this zone, so it MUST match the device's "
            "actual clock. The server never changes the device clock."
        ),
    )

    payroll_cycle_start_day = models.PositiveSmallIntegerField(
        default=23,
        validators=[MinValueValidator(1), MaxValueValidator(28)],
        verbose_name="Payroll Cycle Start Day",
        help_text=(
            "Day of the month the payroll cycle begins (in the previous month). "
            "Default 23 means each payroll month runs from the 23rd of the previous "
            "month to the (start day − 1) of the payroll month — e.g. 23rd → 22nd."
        ),
    )

    class Meta:
        verbose_name = "System Settings"
        verbose_name_plural = "⚙ System Settings"

    def __str__(self):
        return f"Display timezone: {self.display_timezone}"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)
        cache.delete(self._CACHE_KEY)

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    @classmethod
    def get_display_timezone(cls) -> str:
        cached = cache.get(cls._CACHE_KEY)
        if cached:
            return cached
        tz = cls.get().display_timezone
        cache.set(cls._CACHE_KEY, tz, 120)
        return tz

    @classmethod
    def get_payroll_cycle_start_day(cls) -> int:
        try:
            return cls.get().payroll_cycle_start_day or 23
        except Exception:
            return 23

    @classmethod
    def get_device_timezone(cls) -> str:
        try:
            return cls.get().device_timezone or "Asia/Karachi"
        except Exception:
            return "Asia/Karachi"
