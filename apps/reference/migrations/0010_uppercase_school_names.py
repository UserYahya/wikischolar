# School names (and their aliases) are stored in capitals from now on (School.save / SchoolAlias.save);
# this converts the existing rows. Matching is unaffected: normalised names are lower-case anyway.
from django.db import migrations
from django.db.models.functions import Upper


def forwards(apps, schema_editor):
    apps.get_model("reference", "School").objects.update(name=Upper("name"))
    apps.get_model("reference", "SchoolAlias").objects.update(alias_text=Upper("alias_text"))


class Migration(migrations.Migration):
    dependencies = [("reference", "0009_school_government_data")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
