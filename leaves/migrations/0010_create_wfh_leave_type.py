from django.db import migrations


def create_wfh_leave_type(apps, schema_editor):
    LeaveType = apps.get_model("leaves", "LeaveType")
    LeaveType.objects.get_or_create(
        name="Work From Home",
        defaults={
            "is_paid": False,
            "is_wfh": True,
            "default_days": 0,
            "requires_attachment": False,
            "available_for_probation": True,
            "is_active": True,
        },
    )


def reverse_wfh_leave_type(apps, schema_editor):
    LeaveType = apps.get_model("leaves", "LeaveType")
    LeaveType.objects.filter(name="Work From Home", is_wfh=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("leaves", "0009_short_leave"),
    ]

    operations = [
        migrations.RunPython(create_wfh_leave_type, reverse_wfh_leave_type),
    ]
