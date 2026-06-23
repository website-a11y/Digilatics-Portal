from django.db import migrations, models


def seed_from_existing(apps, schema_editor):
    """Seed managed lists from department/designation values already in use."""
    EmployeeProfile = apps.get_model("accounts", "EmployeeProfile")
    Department = apps.get_model("accounts", "Department")
    Designation = apps.get_model("accounts", "Designation")

    depts = (
        EmployeeProfile.objects.exclude(department__in=["", "-"])
        .values_list("department", flat=True).distinct()
    )
    for name in depts:
        Department.objects.get_or_create(name=name.strip())

    desigs = (
        EmployeeProfile.objects.exclude(designation__in=["", "-"])
        .values_list("designation", flat=True).distinct()
    )
    for name in desigs:
        Designation.objects.get_or_create(name=name.strip())


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0006_payment_mode_choices_cnic_blank"),
    ]

    operations = [
        migrations.CreateModel(
            name="Department",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=120, unique=True)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"ordering": ["name"]},
        ),
        migrations.CreateModel(
            name="Designation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=120, unique=True)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"ordering": ["name"]},
        ),
        migrations.RunPython(seed_from_existing, noop),
    ]
