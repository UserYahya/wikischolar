# The government's district and thana lists (BANBEIS e-survey 2024, plus newer upazilas, cantonments
# and "Other thana") replace the old "Upazila / Area" list in an existing database. See
# apps/reference/thana_migration.py. A new install has no districts yet, so this does nothing and
# `manage.py seed_reference` loads the new lists. Not reversible: restore the pre-deploy backup instead.
from django.db import migrations


def forwards(apps, schema_editor):
    from apps.reference import thana_migration
    seed, mapping = thana_migration.load()
    print()
    thana_migration.apply(
        District=apps.get_model("reference", "District"), Thana=apps.get_model("reference", "Thana"),
        School=apps.get_model("reference", "School"), Student=apps.get_model("registration", "Student"),
        AuditLog=apps.get_model("core", "AuditLog"), seed=seed, mapping=mapping)


class Migration(migrations.Migration):
    dependencies = [("reference", "0006_rename_upazila_to_thana"), ("registration", "0009_rename_upazila_to_thana"),
                    ("core", "0002_integrity_triggers")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
