from decimal import Decimal
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("leaves", "0007_wfh"),
    ]

    operations = [
        migrations.CreateModel(
            name="WFHPolicy",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("is_enabled", models.BooleanField(default=True, verbose_name="WFH programme enabled", help_text="Turn off to disable WFH applications company-wide.")),
                ("monthly_accrual_days", models.DecimalField(decimal_places=2, default=Decimal("2"), max_digits=4, verbose_name="Days accrued per month", help_text="How many WFH days each employee earns every calendar month.")),
                ("max_balance", models.DecimalField(decimal_places=2, default=Decimal("5"), max_digits=4, verbose_name="Maximum balance (cap)", help_text="Maximum WFH days an employee can accumulate at any one time.")),
                ("rollover_enabled", models.BooleanField(default=True, verbose_name="Unused days roll over", help_text="When ON, unused WFH days carry forward to the next month (up to the cap). When OFF, the balance resets to the monthly accrual at the start of each month.")),
                ("max_days_per_request", models.DecimalField(decimal_places=2, default=Decimal("5"), max_digits=4, verbose_name="Max days per single request", help_text="Maximum number of WFH days an employee can request in one go.")),
                ("notes", models.TextField(blank=True, verbose_name="Policy notes", help_text="Internal notes about the WFH policy (not shown to employees).")),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "WFH Policy",
                "verbose_name_plural": "WFH Policy",
            },
        ),
    ]
