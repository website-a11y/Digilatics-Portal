from django.db import migrations


def set_annual_no_backdate(apps, schema_editor):
    """Annual/Planned Leave must be requested in advance — disable backdating.

    All other leave types keep allow_backdated=True (the model default) so an
    employee can record, e.g., yesterday's sick/casual absence when back in office.
    """
    LeaveType = apps.get_model("leaves", "LeaveType")
    LeaveType.objects.filter(name="Annual/Planned Leave").update(allow_backdated=False)


def reverse(apps, schema_editor):
    LeaveType = apps.get_model("leaves", "LeaveType")
    LeaveType.objects.filter(name="Annual/Planned Leave").update(allow_backdated=True)


class Migration(migrations.Migration):

    dependencies = [
        ("leaves", "0013_leavetype_allow_backdated"),
    ]

    operations = [
        migrations.RunPython(set_annual_no_backdate, reverse),
    ]
