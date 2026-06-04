from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("attendance", "0005_attendance_policy_and_schedule_times"),
    ]

    operations = [
        migrations.CreateModel(
            name="Shift",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=120, unique=True)),
                ("start_time", models.TimeField()),
                ("end_time", models.TimeField()),
                ("is_active", models.BooleanField(default=True)),
                ("notes", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Shift",
                "verbose_name_plural": "Shifts",
                "ordering": ["start_time", "name"],
            },
        ),
    ]
