from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("leaves", "0010_create_wfh_leave_type"),
    ]

    operations = [
        migrations.AlterField(
            model_name="shortleaverequest",
            name="period",
            field=models.CharField(
                max_length=20,
                blank=True,
                default="",
                choices=[("Morning", "Morning (late start)"), ("Afternoon", "Afternoon (early leaving)")],
            ),
        ),
    ]
