from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("attendance", "0012_alter_attendancerecord_status"),
    ]

    operations = [
        migrations.CreateModel(
            name="SystemSetting",
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
                    "display_timezone",
                    models.CharField(
                        choices=[
                            ("America/New_York",    "Eastern Time (ET)  —  UTC-5 / UTC-4"),
                            ("America/Chicago",     "Central Time (CT)  —  UTC-6 / UTC-5"),
                            ("America/Denver",      "Mountain Time (MT)  —  UTC-7 / UTC-6"),
                            ("America/Los_Angeles", "Pacific Time (PT)  —  UTC-8 / UTC-7"),
                            ("America/Phoenix",     "Arizona (MST, no DST)  —  UTC-7"),
                            ("Asia/Karachi",        "Pakistan Standard Time (PKT)  —  UTC+5"),
                            ("Asia/Kolkata",        "India Standard Time (IST)  —  UTC+5:30"),
                            ("Asia/Dubai",          "Gulf Standard Time (GST)  —  UTC+4"),
                            ("Asia/Riyadh",         "Arabia Standard Time (AST)  —  UTC+3"),
                            ("Europe/London",       "Greenwich / British Time (GMT/BST)  —  UTC+0/+1"),
                            ("Europe/Paris",        "Central European Time (CET)  —  UTC+1/+2"),
                            ("UTC",                 "Coordinated Universal Time (UTC)  —  UTC+0"),
                        ],
                        default="America/New_York",
                        help_text=(
                            "All attendance check-in/out times and leave times across the portal "
                            "and admin will be converted and displayed in this timezone."
                        ),
                        max_length=100,
                        verbose_name="Display Timezone",
                    ),
                ),
            ],
            options={
                "verbose_name": "System Settings",
                "verbose_name_plural": "⚙ System Settings",
            },
        ),
    ]
