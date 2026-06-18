def display_timezone(request):
    """
    Injects display_timezone (IANA string) and display_tz_label (short label)
    into every template context so templates can show timezone-aware info
    without needing to load the tag library.
    """
    try:
        from attendance.models import SystemSetting
        from attendance.tz_utils import get_display_tz_label
        tz = SystemSetting.get_display_timezone()
        label = get_display_tz_label()
    except Exception:
        tz = "America/New_York"
        label = "ET"
    return {
        "display_timezone": tz,
        "display_tz_label": label,
    }
