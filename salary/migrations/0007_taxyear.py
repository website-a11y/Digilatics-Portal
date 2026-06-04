from datetime import date

import django.db.models.deletion
from django.db import migrations, models


def create_tax_years_from_slabs(apps, schema_editor):
    SalaryTaxSlab = apps.get_model("salary", "SalaryTaxSlab")
    TaxYear = apps.get_model("salary", "TaxYear")

    from collections import defaultdict
    groups = defaultdict(list)
    for slab in SalaryTaxSlab.objects.all():
        groups[slab.fiscal_year].append(slab)

    for fiscal_year, slabs in groups.items():
        earliest = min(s.effective_from for s in slabs)
        # Use effective_to / is_active from the slab with the earliest effective_from
        anchor = min(slabs, key=lambda s: s.effective_from)
        ty = TaxYear.objects.create(
            fiscal_year=fiscal_year,
            effective_from=earliest,
            effective_to=anchor.effective_to,
            is_active=anchor.is_active,
            notes=anchor.notes,
        )
        for slab in slabs:
            slab.tax_year_id = ty.pk
            slab.save(update_fields=["tax_year_id"])


def reverse_tax_years(apps, schema_editor):
    SalaryTaxSlab = apps.get_model("salary", "SalaryTaxSlab")
    for slab in SalaryTaxSlab.objects.select_related("tax_year").all():
        if slab.tax_year_id:
            ty = slab.tax_year
            slab.fiscal_year = ty.fiscal_year
            slab.effective_from = ty.effective_from
            slab.effective_to = ty.effective_to
            slab.is_active = ty.is_active
            slab.notes = ty.notes
            slab.save(update_fields=["fiscal_year", "effective_from", "effective_to", "is_active", "notes"])


class Migration(migrations.Migration):

    dependencies = [
        ("salary", "0006_merge"),
    ]

    operations = [
        # 1. Create TaxYear table
        migrations.CreateModel(
            name="TaxYear",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("fiscal_year", models.CharField(help_text="e.g. 2025-2026", max_length=20, unique=True)),
                ("effective_from", models.DateField()),
                ("effective_to", models.DateField(blank=True, null=True)),
                ("is_active", models.BooleanField(default=True)),
                ("notes", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Tax Year",
                "verbose_name_plural": "Tax Years",
                "ordering": ["-effective_from"],
            },
        ),
        migrations.AddConstraint(
            model_name="taxyear",
            constraint=models.CheckConstraint(
                check=models.Q(effective_to__isnull=True) | models.Q(effective_to__gte=models.F("effective_from")),
                name="tax_year_effective_to_gte_from",
            ),
        ),

        # 2. Add nullable FK on SalaryTaxSlab
        migrations.AddField(
            model_name="salarytaxslab",
            name="tax_year",
            field=models.ForeignKey(
                null=True,
                blank=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="slabs",
                to="salary.taxyear",
            ),
        ),

        # 3. Populate FK from existing fiscal_year data
        migrations.RunPython(create_tax_years_from_slabs, reverse_code=reverse_tax_years),

        # 4. Make tax_year non-nullable
        migrations.AlterField(
            model_name="salarytaxslab",
            name="tax_year",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="slabs",
                to="salary.taxyear",
            ),
        ),

        # 5. Remove old constraint that referenced effective_from / effective_to on slab
        migrations.RemoveConstraint(
            model_name="salarytaxslab",
            name="salary_tax_slab_effective_to_gte_from",
        ),

        # 6. Drop old fields from SalaryTaxSlab
        migrations.RemoveField(model_name="salarytaxslab", name="fiscal_year"),
        migrations.RemoveField(model_name="salarytaxslab", name="effective_from"),
        migrations.RemoveField(model_name="salarytaxslab", name="effective_to"),
        migrations.RemoveField(model_name="salarytaxslab", name="is_active"),
        migrations.RemoveField(model_name="salarytaxslab", name="notes"),

        # 7. Fix ordering (no longer has effective_from on slab)
        migrations.AlterModelOptions(
            name="salarytaxslab",
            options={"ordering": ["sort_order", "annual_min_income"]},
        ),
    ]
