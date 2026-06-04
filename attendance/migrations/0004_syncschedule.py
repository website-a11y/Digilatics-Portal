from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("attendance", "0003_deviceemployee"),
    ]

    operations = [
        migrations.CreateModel(
            name="SyncSchedule",
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
                    "sync_time_1",
                    models.TimeField(
                        default="18:30",
                        help_text="First sync time (24-hour format)",
                    ),
                ),
                (
                    "sync_time_2",
                    models.TimeField(
                        default="02:30",
                        help_text="Second sync time (24-hour format)",
                    ),
                ),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Sync Schedule",
                "verbose_name_plural": "Sync Schedule",
            },
        ),
    ]
