from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("attendance", "0010_merge_attendance_0009s"),
    ]

    operations = [
        migrations.CreateModel(
            name="DeviceSyncFlag",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("full_sync_from", models.DateField(blank=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Device Sync Flag",
                "verbose_name_plural": "Device Sync Flags",
            },
        ),
    ]
