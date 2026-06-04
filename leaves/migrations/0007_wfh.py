from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0001_initial"),
        ("leaves", "0006_add_manager_approved_status_and_field"),
    ]

    operations = [
        migrations.AddField(
            model_name="leavetype",
            name="is_wfh",
            field=models.BooleanField(
                default=False,
                verbose_name="Work from Home type",
                help_text=(
                    "When enabled, requests use the monthly WFH balance (2 days/month, max 5) "
                    "instead of a standard leave allocation."
                ),
            ),
        ),
        migrations.CreateModel(
            name="WFHBalance",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "employee",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="wfh_balance",
                        to="accounts.employeeprofile",
                    ),
                ),
                ("balance", models.DecimalField(decimal_places=2, default=0, max_digits=5)),
                ("last_accrued_year", models.PositiveIntegerField(blank=True, null=True)),
                ("last_accrued_month", models.PositiveIntegerField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "WFH Balance",
                "verbose_name_plural": "WFH Balances",
                "ordering": ["employee__full_name"],
            },
        ),
    ]
