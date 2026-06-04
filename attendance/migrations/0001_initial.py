import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("accounts", "0002_alter_employeeprofile_employment_type"),
    ]

    operations = [
        migrations.CreateModel(
            name="PublicHoliday",
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
                ("name", models.CharField(max_length=200)),
                ("date", models.DateField(unique=True)),
                ("description", models.TextField(blank=True)),
                ("is_active", models.BooleanField(default=True)),
            ],
            options={
                "verbose_name": "Public Holiday",
                "verbose_name_plural": "Public Holidays",
                "ordering": ["date"],
            },
        ),
        migrations.CreateModel(
            name="AttendanceRecord",
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
                ("date", models.DateField()),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("present", "Present"),
                            ("absent", "Absent"),
                            ("on_leave_paid", "On Leave (Paid)"),
                            ("on_leave_unpaid", "On Leave (Unpaid)"),
                            ("on_hourly_leave", "On Hourly Leave"),
                            ("public_holiday", "Public Holiday"),
                            ("half_day", "Half Day"),
                        ],
                        default="present",
                        max_length=20,
                    ),
                ),
                ("check_in", models.TimeField(blank=True, null=True, verbose_name="Check In")),
                ("check_out", models.TimeField(blank=True, null=True, verbose_name="Check Out")),
                ("notes", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "employee",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="attendance_records",
                        to="accounts.employeeprofile",
                    ),
                ),
            ],
            options={
                "verbose_name": "Attendance Record",
                "verbose_name_plural": "Attendance Records",
                "ordering": ["-date", "employee__full_name"],
                "unique_together": {("employee", "date")},
            },
        ),
    ]
