from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("attendance", "0015_systemsetting_payroll_cycle_start_day"),
    ]

    operations = [
        migrations.AddField(
            model_name="systemsetting",
            name="device_timezone",
            field=models.CharField(
                max_length=100,
                default="Asia/Karachi",
                verbose_name="Device Timezone",
                choices=[
                    ("America/New_York", "Eastern Time (ET)  —  UTC-5 / UTC-4"),
                    ("America/Chicago", "Central Time (CT)  —  UTC-6 / UTC-5"),
                    ("America/Denver", "Mountain Time (MT)  —  UTC-7 / UTC-6"),
                    ("America/Los_Angeles", "Pacific Time (PT)  —  UTC-8 / UTC-7"),
                    ("America/Phoenix", "Arizona (MST, no DST)  —  UTC-7"),
                    ("Asia/Karachi", "Pakistan Standard Time (PKT)  —  UTC+5"),
                    ("Asia/Kolkata", "India Standard Time (IST)  —  UTC+5:30"),
                    ("Asia/Dubai", "Gulf Standard Time (GST)  —  UTC+4"),
                    ("Asia/Riyadh", "Arabia Standard Time (AST)  —  UTC+3"),
                    ("Europe/London", "Greenwich / British Time (GMT/BST)  —  UTC+0/+1"),
                    ("Europe/Paris", "Central European Time (CET)  —  UTC+1/+2"),
                    ("UTC", "Coordinated Universal Time (UTC)  —  UTC+0"),
                ],
                help_text=(
                    "The timezone the biometric device's clock is set to. Incoming punch "
                    "timestamps are interpreted in this zone, so it MUST match the device's "
                    "actual clock. The server never changes the device clock."
                ),
            ),
        ),
    ]
