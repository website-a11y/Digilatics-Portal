import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("attendance", "0014_alter_systemsetting_display_timezone"),
    ]

    operations = [
        migrations.AddField(
            model_name="systemsetting",
            name="payroll_cycle_start_day",
            field=models.PositiveSmallIntegerField(
                default=23,
                validators=[
                    django.core.validators.MinValueValidator(1),
                    django.core.validators.MaxValueValidator(28),
                ],
                help_text=(
                    "Day of the month the payroll cycle begins (in the previous month). "
                    "Default 23 means each payroll month runs from the 23rd of the previous "
                    "month to the (start day − 1) of the payroll month — e.g. 23rd → 22nd."
                ),
                verbose_name="Payroll Cycle Start Day",
            ),
        ),
    ]
