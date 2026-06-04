from django.db import migrations, models


def copy_holiday_date(apps, schema_editor):
    PublicHoliday = apps.get_model("attendance", "PublicHoliday")
    for h in PublicHoliday.objects.all():
        h.start_date = h.date
        h.save(update_fields=["start_date"])


class Migration(migrations.Migration):

    dependencies = [
        ("attendance", "0007_companywfhday"),
    ]

    operations = [
        # ── PublicHoliday: add start_date (nullable first), data-migrate, remove date ──
        migrations.AddField(
            model_name="publicholiday",
            name="start_date",
            field=models.DateField(null=True, blank=True),
        ),
        migrations.AddField(
            model_name="publicholiday",
            name="end_date",
            field=models.DateField(null=True, blank=True, help_text="Leave blank for a single-day holiday."),
        ),
        migrations.RunPython(copy_holiday_date, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="publicholiday",
            name="start_date",
            field=models.DateField(),
        ),
        migrations.RemoveField(
            model_name="publicholiday",
            name="date",
        ),
        migrations.AlterModelOptions(
            name="publicholiday",
            options={"ordering": ["start_date"], "verbose_name": "Public Holiday", "verbose_name_plural": "Public Holidays"},
        ),

        # ── CompanyWFHDay: remove unique date, add start_date + end_date ──
        migrations.RemoveField(
            model_name="companywfhday",
            name="date",
        ),
        migrations.AddField(
            model_name="companywfhday",
            name="start_date",
            field=models.DateField(default="2025-01-01"),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="companywfhday",
            name="end_date",
            field=models.DateField(null=True, blank=True, help_text="Leave blank for a single-day WFH declaration."),
        ),
        migrations.AlterModelOptions(
            name="companywfhday",
            options={"ordering": ["-start_date"], "verbose_name": "Company WFH Day", "verbose_name_plural": "Company WFH Days"},
        ),
    ]
