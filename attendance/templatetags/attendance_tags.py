"""
Template tags and filters for attendance time display.

Usage in templates:
    {% load attendance_tags %}

    {# Convert a stored ET time to the display timezone #}
    {{ record.check_in|tz_time:record.date }}

    {# 24-hour version for JavaScript #}
    {{ record.check_in|tz_time_24:record.date }}

    {# Short timezone label, e.g. "ET", "PKT" #}
    {% tz_label %}
"""
from django import template

register = template.Library()


@register.filter(name="tz_time")
def tz_time(time_val, record_date=None):
    """
    Convert a naive time (stored as ET) to the admin-selected display timezone.
    Pass the record's date as the filter argument for DST-accurate conversion.

        {{ record.check_in|tz_time:record.date }}
    """
    from attendance.tz_utils import convert_time
    return convert_time(time_val, record_date)


@register.filter(name="tz_time_24")
def tz_time_24(time_val, record_date=None):
    """
    24-hour version — returns 'HH:MM' string for use in JavaScript.

        {{ record.check_in|tz_time_24:record.date }}
    """
    from attendance.tz_utils import convert_time_24
    return convert_time_24(time_val, record_date)


@register.simple_tag
def tz_label():
    """Returns short label of current display timezone, e.g. 'ET', 'PKT'."""
    from attendance.tz_utils import get_display_tz_label
    return get_display_tz_label()


@register.simple_tag
def tz_name():
    """Returns the full IANA timezone name, e.g. 'America/New_York'."""
    try:
        from attendance.models import SystemSetting
        return SystemSetting.get_display_timezone()
    except Exception:
        return "America/New_York"
