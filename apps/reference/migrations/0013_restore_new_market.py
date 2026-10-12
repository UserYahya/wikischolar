# Dhaka's "New Market" thana is back: it wasn't in the first BANBEIS sheet (so 0007 archived the old
# row), but the "School and College" sheet has schools there. The archived row is restored, keeping its
# id and Bangla, as a plain thana; a database without it gets a new row. Nothing pointed at it while
# it was archived (0007 moved anything on it to "Other thana").
from django.db import migrations
from django.utils import timezone


def forwards(apps, schema_editor):
    District = apps.get_model("reference", "District")
    Thana = apps.get_model("reference", "Thana")
    dhaka = District.objects.filter(code="dhaka").first()
    if dhaka is None:  # a new install: seed_reference adds it
        return
    rows = getattr(Thana, "all_objects", Thana.objects)  # archived rows too (a migration's manager sees them)
    row = rows.filter(district=dhaka, name="New Market").first()
    if row is None:
        Thana.objects.create(district=dhaka, name="New Market", name_bn="নিউ মার্কেট")
    else:
        row.is_deleted, row.deleted_at, row.deleted_by = False, None, None
        row.group, row.group_bn = "", ""
        row.name_bn = row.name_bn or "নিউ মার্কেট"
        row.updated_at = timezone.now()
        row.save()


class Migration(migrations.Migration):
    dependencies = [("reference", "0012_school_and_college_choices")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
