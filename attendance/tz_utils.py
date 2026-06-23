"""
Timezone conversion utilities for displaying stored times in the admin-configured
display timezone.

All check_in / check_out / leave times are stored as naive TimeField values
representing Eastern Time (America/New_York).  Use the helpers here to convert
them to whatever timezone the admin has chosen in System Settings.
"""
from datetime import datetime, time as time_type
from zoneinfo import ZoneInfo

from django.utils import timezone as dj_tz

_STORED_TZ = ZoneInfo("America/New_York")  # All times are stored as ET


def _get_display_tz() -> ZoneInfo:
    try:
        from attendance.models import SystemSetting
        return ZoneInfo(SystemSetting.get_display_timezone())
    except Exception:
        return _STORED_TZ


# Punches before this device-local hour belong to the previous day's workday.
# Shifts here start in the afternoon and end after midnight (e.g. 4pm–1am), so a
# 1 AM punch is the prior day's check-out, not a new workday.
WORKDAY_BOUNDARY_HOUR = 12


def get_device_zone() -> ZoneInfo:
    """The biometric device's clock timezone (admin setting). Used to interpret
    incoming punch timestamps. Falls back to PKT."""
    try:
        from attendance.models import SystemSetting
        return ZoneInfo(SystemSetting.get_device_timezone())
    except Exception:
        return ZoneInfo("Asia/Karachi")


def device_workday(local_dt, boundary_hour: int = WORKDAY_BOUNDARY_HOUR):
    """Return the workday date for a punch given its DEVICE-LOCAL datetime.

    `local_dt` must already be in device-local time (naive or aware). A punch
    before `boundary_hour` rolls back to the previous calendar day so an overnight
    shift's after-midnight punches stay on the check-in day.
    """
    from datetime import timedelta
    workday = local_dt.date()
    if local_dt.hour < boundary_hour:
        workday = workday - timedelta(days=1)
    return workday


def convert_time(time_val, record_date=None, fmt: str = "%I:%M %p") -> str:
    """
    Convert a naive time (stored as ET) to the system display timezone.

    Args:
        time_val:    A datetime.time object from a TimeField.
        record_date: The date the record belongs to (for DST accuracy).
                     Falls back to today's ET date if not supplied.
        fmt:         strftime format string.

    Returns:
        Formatted time string in the display timezone, e.g. "9:30 AM".
    """
    if not time_val or not isinstance(time_val, time_type):
        return ""

    display_tz = _get_display_tz()
    d = record_date if record_date else dj_tz.localdate()

    aware = datetime.combine(d, time_val).replace(tzinfo=_STORED_TZ)
    converted = aware.astimezone(display_tz)
    result = converted.strftime(fmt)
    # Strip leading zero: "09:30 AM" → "9:30 AM"
    if fmt == "%I:%M %p" and result.startswith("0"):
        result = result[1:]
    return result


def convert_time_24(time_val, record_date=None) -> str:
    """24-hour version, e.g. '09:30', used for JavaScript."""
    return convert_time(time_val, record_date, fmt="%H:%M")


def get_display_tz_label() -> str:
    """
    Returns a short human-readable label for the current display timezone,
    e.g. 'ET', 'PKT', 'IST'.
    """
    try:
        from attendance.models import SystemSetting
        tz_str = SystemSetting.get_display_timezone()
    except Exception:
        return "ET"

    _LABELS = {
        "America/New_York":    "ET",
        "America/Chicago":     "CT",
        "America/Denver":      "MT",
        "America/Los_Angeles": "PT",
        "America/Phoenix":     "MST",
        "Asia/Karachi":        "PKT",
        "Asia/Kolkata":        "IST",
        "Asia/Dubai":          "GST",
        "Asia/Riyadh":         "AST",
        "Europe/London":       "GMT",
        "Europe/Paris":        "CET",
        "UTC":                 "UTC",
    }
    return _LABELS.get(tz_str, tz_str.split("/")[-1])
