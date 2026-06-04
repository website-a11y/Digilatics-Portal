import django.db.models.deletion
from django.db import migrations, models


def create_shifts_from_schedules(apps, schema_editor):
    EmployeeProfile = apps.get_model("accounts", "EmployeeProfile")
    Shift = apps.get_model("attendance", "Shift")

    # Group employees by unique (checkin, checkout) pair
    pairs = {}
    for emp in EmployeeProfile.objects.exclude(
        scheduled_checkin__isnull=True, scheduled_checkout__isnull=True
    ):
        key = (emp.scheduled_checkin, emp.scheduled_checkout)
        if None in key:
            continue
        if key not in pairs:
            pairs[key] = []
        pairs[key].append(emp)

    for (checkin, checkout), employees in pairs.items():
        # Format times as HH:MM for the name
        def fmt(t):
            h = t.hour
            m = t.minute
            period = "AM" if h < 12 else "PM"
            h12 = h % 12 or 12
            return f"{h12}:{m:02d} {period}"

        name = f"Shift {fmt(checkin)} to {fmt(checkout)}"
        # Ensure unique name
        base_name = name
        counter = 1
        while Shift.objects.filter(name=name).exists():
            name = f"{base_name} ({counter})"
            counter += 1

        shift = Shift.objects.create(
            name=name,
            start_time=checkin,
            end_time=checkout,
            is_active=True,
        )
        for emp in employees:
            emp.shift_master_id = shift.pk
            emp.save(update_fields=["shift_master_id"])


def reverse_shifts(apps, schema_editor):
    EmployeeProfile = apps.get_model("accounts", "EmployeeProfile")
    EmployeeProfile.objects.all().update(shift_master=None)


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0003_attendance_policy_and_schedule_times"),
        ("attendance", "0006_shift"),
    ]

    operations = [
        # 1. Add nullable FK
        migrations.AddField(
            model_name="employeeprofile",
            name="shift_master",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="employees",
                to="attendance.shift",
                verbose_name="Shift",
                help_text="Assign a shift template — check-in/out times sync automatically.",
            ),
        ),
        # 2. Make shift CharField blank-able (was required)
        migrations.AlterField(
            model_name="employeeprofile",
            name="shift",
            field=models.CharField(max_length=80, blank=True),
        ),
        # 3. Populate FK from existing scheduled times
        migrations.RunPython(create_shifts_from_schedules, reverse_code=reverse_shifts),
    ]
