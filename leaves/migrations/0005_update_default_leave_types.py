from django.db import migrations


def update_default_leave_types(apps, schema_editor):
    LeaveType = apps.get_model("leaves", "LeaveType")

    leave_type_updates = [
        {
            "old_names": ["Annual Leave"],
            "name": "Annual/Planned Leave",
            "is_paid": True,
            "default_days": 10,
            "requires_attachment": False,
            "available_for_probation": False,
            "is_active": True,
        },
        {
            "old_names": ["Casual Leave"],
            "name": "Casual Leave",
            "is_paid": True,
            "default_days": 6,
            "requires_attachment": False,
            "available_for_probation": False,
            "is_active": True,
        },
        {
            "old_names": ["Sick/Medical Leave"],
            "name": "Sick/Medical Leave",
            "is_paid": True,
            "default_days": 8,
            "requires_attachment": False,
            "available_for_probation": False,
            "is_active": True,
        },
        {
            "old_names": [],
            "name": "Special Sick Leave",
            "is_paid": True,
            "default_days": 45,
            "requires_attachment": True,
            "available_for_probation": False,
            "is_active": True,
        },
        {
            "old_names": ["Marriage Leave"],
            "name": "Marriage Leave",
            "is_paid": True,
            "default_days": 3,
            "requires_attachment": False,
            "available_for_probation": False,
            "is_active": True,
        },
        {
            "old_names": ["Birthday Leave"],
            "name": "Birthday Leave",
            "is_paid": True,
            "default_days": 1,
            "requires_attachment": False,
            "available_for_probation": False,
            "is_active": True,
        },
        {
            "old_names": ["Maternity Leave"],
            "name": "Maternity Leave",
            "is_paid": True,
            "default_days": 30,
            "requires_attachment": False,
            "available_for_probation": False,
            "is_active": True,
        },
        {
            "old_names": ["Paternity Leave"],
            "name": "Paternity Leave",
            "is_paid": True,
            "default_days": 10,
            "requires_attachment": False,
            "available_for_probation": False,
            "is_active": True,
        },
        {
            "old_names": ["Bereavement Leave"],
            "name": "Bereavement Leave",
            "is_paid": True,
            "default_days": 2,
            "requires_attachment": False,
            "available_for_probation": False,
            "is_active": True,
        },
        {
            "old_names": [],
            "name": "Leave Without Pay (LWOP)",
            "is_paid": False,
            "default_days": 0,
            "requires_attachment": False,
            "available_for_probation": False,
            "is_active": True,
        },
        {
            "old_names": [],
            "name": "Probationary Leave",
            "is_paid": False,
            "default_days": 6,
            "requires_attachment": False,
            "available_for_probation": True,
            "is_active": True,
        },
    ]

    for leave_type_data in leave_type_updates:
        leave_type, created = LeaveType.objects.get_or_create(
            name=leave_type_data["name"],
            defaults={
                "is_paid": leave_type_data["is_paid"],
                "default_days": leave_type_data["default_days"],
                "requires_attachment": leave_type_data["requires_attachment"],
                "available_for_probation": leave_type_data["available_for_probation"],
                "is_active": leave_type_data["is_active"],
            },
        )
        if not created:
            leave_type.is_paid = leave_type_data["is_paid"]
            leave_type.default_days = leave_type_data["default_days"]
            leave_type.requires_attachment = leave_type_data["requires_attachment"]
            leave_type.available_for_probation = leave_type_data["available_for_probation"]
            leave_type.is_active = leave_type_data["is_active"]
            leave_type.save()

        if leave_type_data["old_names"]:
            for old_name in leave_type_data["old_names"]:
                if old_name != leave_type_data["name"]:
                    old = LeaveType.objects.filter(name=old_name).first()
                    if old and old.pk != leave_type.pk:
                        old.name = f"{old.name} (legacy)"
                        old.is_active = False
                        old.save()


def reverse_update_default_leave_types(apps, schema_editor):
    LeaveType = apps.get_model("leaves", "LeaveType")
    names = [
        "Annual/Planned Leave",
        "Special Sick Leave",
        "Leave Without Pay (LWOP)",
        "Probationary Leave",
    ]
    LeaveType.objects.filter(name__in=names).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("leaves", "0004_add_default_leave_types"),
    ]

    operations = [
        migrations.RunPython(update_default_leave_types, reverse_update_default_leave_types),
    ]
