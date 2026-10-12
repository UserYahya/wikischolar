# students.upazila_id becomes students.thana_id (renamed in place), with its composite FK.
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("registration", "0008_banner_leaflet_label"), ("reference", "0006_rename_upazila_to_thana")]

    operations = [
        migrations.RenameField("student", "upazila", "thana"),
        # The index follows the column in Postgres; only the state's field list changes.
        migrations.SeparateDatabaseAndState(state_operations=[
            migrations.RemoveIndex("student", "student_location_idx"),
            migrations.AddIndex("student", models.Index(fields=["district", "thana"], name="student_location_idx")),
        ]),
        migrations.RunSQL(
            "ALTER TABLE students RENAME CONSTRAINT students_upazila_in_district TO students_thana_in_district;",
            "ALTER TABLE students RENAME CONSTRAINT students_thana_in_district TO students_upazila_in_district;"),
    ]
