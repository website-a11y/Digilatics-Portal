from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0001_initial"),
        ("attendance", "0002_attendancerecord_leave_request"),
    ]

    operations = [
        migrations.CreateModel(
            name="DeviceEmployee",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "device_user_id",
                    models.PositiveIntegerField(
                        help_text="The numeric user ID enrolled on the biometric device (starts from 10000).",
                        unique=True,
                        verbose_name="Device User ID",
                    ),
                ),
                (
                    "employee",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="device_mapping",
                        to="accounts.employeeprofile",
                    ),
                ),
            ],
            options={
                "verbose_name": "Device Employee Mapping",
                "verbose_name_plural": "Device Employee Mappings",
                "ordering": ["device_user_id"],
            },
        ),
    ]
