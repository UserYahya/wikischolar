from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.operations import TrigramExtension
from django.db import migrations

from apps.core.sql import forbid_delete, run


class Migration(migrations.Migration):
    dependencies = [("reference", "0001_initial"), ("core", "0002_integrity_triggers")]
    operations = [
        TrigramExtension(),
        migrations.AddIndex("school", GinIndex(fields=["name_normalized"], name="school_name_trgm",
                                               opclasses=["gin_trgm_ops"])),
        migrations.AddIndex("schoolalias", GinIndex(fields=["alias_normalized"], name="alias_text_trgm",
                                                    opclasses=["gin_trgm_ops"])),
        *run(migrations, [forbid_delete(t) for t in ("regions", "districts", "upazilas", "schools", "school_aliases")]),
    ]
