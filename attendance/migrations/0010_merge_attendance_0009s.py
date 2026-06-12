from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("attendance", "0009_alter_attendancerecord_status"),
        ("attendance", "0009_convert_shift_times_to_est"),
    ]

    operations = []
