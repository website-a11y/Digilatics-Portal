from django.db import migrations


def create_default_leave_types(apps, schema_editor):
    LeaveType = apps.get_model("leaves", "LeaveType")
    leave_types = [
        {
            "name": "Annual/Planned Leave",
            "is_paid": True,
            "default_days": 10,
            "requires_attachment": False,
            "available_for_probation": False,
            "is_active": True,
        },
        {
            "name": "Casual Leave",
            "is_paid": True,
            "default_days": 6,
            "requires_attachment": False,
            "available_for_probation": False,
            "is_active": True,
        },
        {
            "name": "Sick/Medical Leave",
            "is_paid": True,
            "default_days": 8,
            "requires_attachment": False,
            "available_for_probation": False,
            "is_active": True,
        },
        {
            "name": "Special Sick Leave",
            "is_paid": True,
            "default_days": 45,
            "requires_attachment": True,
            "available_for_probation": False,
            "is_active": True,
        },
        {
            "name": "Marriage Leave",
            "is_paid": True,
            "default_days": 3,
            "requires_attachment": False,
            "available_for_probation": False,
            "is_active": True,
        },
        {
            "name": "Birthday Leave",
            "is_paid": True,
            "default_days": 1,
            "requires_attachment": False,
            "available_for_probation": False,
            "is_active": True,
        },
        {
            "name": "Maternity Leave",
            "is_paid": True,
            "default_days": 30,
            "requires_attachment": False,
            "available_for_probation": False,
            "is_active": True,
        },
        {
            "name": "Paternity Leave",
            "is_paid": True,
            "default_days": 10,
            "requires_attachment": False,
            "available_for_probation": False,
            "is_active": True,
        },
        {
            "name": "Bereavement Leave",
            "is_paid": True,
            "default_days": 2,
            "requires_attachment": False,
            "available_for_probation": False,
            "is_active": True,
        },
        {
            "name": "Leave Without Pay (LWOP)",
            "is_paid": False,
            "default_days": 0,
            "requires_attachment": False,
            "available_for_probation": False,
            "is_active": True,
        },
        {
            "name": "Probationary Leave",
            "is_paid": False,
            "default_days": 6,
            "requires_attachment": False,
            "available_for_probation": True,
            "is_active": True,
        },
    ]

    for leave_type_data in leave_types:
        LeaveType.objects.update_or_create(
            name=leave_type_data["name"],
            defaults={
                "is_paid": leave_type_data["is_paid"],
                "default_days": leave_type_data["default_days"],
                "requires_attachment": leave_type_data["requires_attachment"],
                "available_for_probation": leave_type_data["available_for_probation"],
                "is_active": leave_type_data["is_active"],
            },
        )


def reverse_default_leave_types(apps, schema_editor):
    LeaveType = apps.get_model("leaves", "LeaveType")
    names = [
        "Annual/Planned Leave",
        "Casual Leave",
        "Sick/Medical Leave",
        "Special Sick Leave",
        "Marriage Leave",
        "Birthday Leave",
        "Maternity Leave",
        "Paternity Leave",
        "Bereavement Leave",
        "Leave Without Pay (LWOP)",
        "Probationary Leave",
    ]
    LeaveType.objects.filter(name__in=names).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("leaves", "0003_leavetype_available_for_probation"),
    ]

    operations = [
        migrations.RunPython(create_default_leave_types, reverse_default_leave_types),
    ]
