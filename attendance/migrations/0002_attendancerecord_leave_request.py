import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("attendance", "0001_initial"),
        ("leaves", "0003_leavetype_available_for_probation"),
    ]

    operations = [
        migrations.AddField(
            model_name="attendancerecord",
            name="leave_request",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="attendance_records",
                to="leaves.leaverequest",
                verbose_name="Leave Request",
            ),
        ),
    ]
