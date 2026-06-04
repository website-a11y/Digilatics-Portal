from decimal import Decimal
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0001_initial"),
        ("leaves", "0008_wfhpolicy"),
    ]

    operations = [
        migrations.CreateModel(
            name="ShortLeavePolicy",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("is_enabled", models.BooleanField(default=True, verbose_name="Short leave enabled")),
                ("max_per_month", models.PositiveSmallIntegerField(default=2, verbose_name="Max short leaves per month")),
                ("min_hours_before_afternoon", models.DecimalField(decimal_places=2, default=Decimal("4"), max_digits=4, verbose_name="Min hours worked before afternoon short leave")),
                ("notes", models.TextField(blank=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"verbose_name": "Short Leave Policy", "verbose_name_plural": "Short Leave Policy"},
        ),
        migrations.CreateModel(
            name="ShortLeaveRequest",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("employee", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="short_leave_requests", to="accounts.employeeprofile")),
                ("date", models.DateField()),
                ("period", models.CharField(max_length=20, choices=[("Morning", "Morning (late start)"), ("Afternoon", "Afternoon (early leaving)")])),
                ("from_time", models.TimeField()),
                ("to_time", models.TimeField()),
                ("reason", models.TextField(blank=True)),
                ("status", models.CharField(max_length=20, default="Pending", choices=[("Pending", "Pending"), ("Manager Approved", "Manager Approved"), ("Approved", "Approved"), ("Rejected", "Rejected"), ("Cancelled", "Cancelled")])),
                ("remarks", models.TextField(blank=True)),
                ("manager_approved_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="manager_approved_short_leaves", to="accounts.employeeprofile")),
                ("approved_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="approved_short_leaves", to="accounts.employeeprofile")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"verbose_name": "Short Leave Request", "verbose_name_plural": "Short Leave Requests", "ordering": ["-date", "-created_at"]},
        ),
    ]
