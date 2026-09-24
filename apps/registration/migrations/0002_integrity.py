from django.db import migrations

from apps.core.sql import append_only, forbid_delete, run

COMPOSITE_FK = (
    "ALTER TABLE students ADD CONSTRAINT students_upazila_in_district "
    "FOREIGN KEY (upazila_id, district_id) REFERENCES upazilas (id, district_id) DEFERRABLE INITIALLY DEFERRED;",
    "ALTER TABLE students DROP CONSTRAINT IF EXISTS students_upazila_in_district;",
)
UNIQUE_ACTIVE_ID = (
    # Guard against the either-or rule being bypassed with whitespace-only values
    "ALTER TABLE students ADD CONSTRAINT student_roll_or_sid_not_blank "
    "CHECK (btrim(class_roll) <> '' OR btrim(student_id_sid) <> '');",
    "ALTER TABLE students DROP CONSTRAINT IF EXISTS student_roll_or_sid_not_blank;",
)


class Migration(migrations.Migration):
    dependencies = [("registration", "0001_initial"), ("reference", "0002_trigram_and_integrity"),
                    ("core", "0002_integrity_triggers")]
    operations = [
        migrations.RunSQL(*COMPOSITE_FK),
        migrations.RunSQL(*UNIQUE_ACTIVE_ID),
        *run(migrations, [forbid_delete("students"), forbid_delete("email_verifications"),
                          append_only("edit_history")]),
    ]
