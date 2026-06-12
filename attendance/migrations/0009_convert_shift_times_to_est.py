"""
Data migration: convert Shift start/end times from PKT (UTC+5) to EST/EDT.

Background
----------
Prior to this migration the portal ran on Asia/Karachi timezone, so admins
entered shift times in PKT (e.g. 3:00 PM PKT, 12:00 AM PKT).  The portal has
since been switched to America/New_York (EST/EDT).  Attendance check-in times
are now stored in EST, so shift times must also be in EST for late/early
detection to work correctly.

Conversion uses 2026-06-01 as the reference date (EDT = UTC-4 in effect).
PKT is UTC+5, EDT is UTC-4 → 9-hour difference.

Guard: if all shifts already start before noon (i.e. they were already
converted, or there is no data), the migration is a no-op.
"""
from datetime import datetime
from zoneinfo import ZoneInfo

from django.db import migrations

PKT = ZoneInfo("Asia/Karachi")
EST = ZoneInfo("America/New_York")
_Y, _M, _D = 2026, 6, 1  # reference date — EDT (UTC-4) is in effect


def _pkt_to_est(naive_time):
    dt_pkt = datetime(_Y, _M, _D, naive_time.hour, naive_time.minute, tzinfo=PKT)
    return dt_pkt.astimezone(EST).time().replace(tzinfo=None)


def convert_shifts(apps, schema_editor):
    Shift = apps.get_model("attendance", "Shift")
    EmployeeProfile = apps.get_model("accounts", "EmployeeProfile")

    shifts = list(Shift.objects.all())
    if not shifts:
        return

    # Guard: if every shift already starts before noon assume already converted.
    if all(s.start_time.hour < 12 for s in shifts):
        return

    for shift in shifts:
        shift.start_time = _pkt_to_est(shift.start_time)
        shift.end_time = _pkt_to_est(shift.end_time)
        shift.save(update_fields=["start_time", "end_time"])

    # Re-sync employees whose scheduled times come from a shift master.
    for emp in EmployeeProfile.objects.filter(shift_master__isnull=False).select_related("shift_master"):
        emp.scheduled_checkin = emp.shift_master.start_time
        emp.scheduled_checkout = emp.shift_master.end_time
        emp.save(update_fields=["scheduled_checkin", "scheduled_checkout"])

    # Also convert employees with manually-overridden times (no shift master).
    for emp in EmployeeProfile.objects.filter(
        shift_master__isnull=True,
        scheduled_checkin__isnull=False,
    ):
        if emp.scheduled_checkin and emp.scheduled_checkin.hour >= 12:
            emp.scheduled_checkin = _pkt_to_est(emp.scheduled_checkin)
            if emp.scheduled_checkout:
                emp.scheduled_checkout = _pkt_to_est(emp.scheduled_checkout)
            emp.save(update_fields=["scheduled_checkin", "scheduled_checkout"])


def reverse_convert(apps, schema_editor):
    # Intentionally left blank — this migration is one-directional.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("attendance", "0008_date_ranges"),
        ("accounts", "__latest__"),
    ]

    operations = [
        migrations.RunPython(convert_shifts, reverse_convert),
    ]
