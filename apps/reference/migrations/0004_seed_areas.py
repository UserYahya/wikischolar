# Adds the "Upazila / Area" rows from data/reference_seed.json to districts that already exist: the
# missing upazila(s), city-corporation thanas, cantonments and one "Other area" per district. Existing
# rows (and anything renamed or archived on the dashboard) are left alone; an existing row with the same
# name only gets its group filled in. On a new install there are no districts yet, so this does nothing
# and `manage.py seed_reference` loads everything instead.
import json
from pathlib import Path

from django.conf import settings
from django.db import migrations


def add_areas(apps, schema_editor):
    District = apps.get_model("reference", "District")
    Upazila = apps.get_model("reference", "Upazila")
    path = Path(settings.BASE_DIR) / "data" / "reference_seed.json"
    if not path.exists():
        return
    districts = {d.code: d for d in District.objects.all()}
    if not districts:
        return
    for d in json.loads(path.read_text(encoding="utf-8"))["districts"]:
        district = districts.get(d["code"])
        if district is None:
            continue
        for u in d.get("upazilas", []):
            Upazila.objects.get_or_create(district=district, name=u["name"], defaults={"name_bn": u.get("name_bn", "")})
        for a in d.get("areas", []):
            obj, created = Upazila.objects.get_or_create(
                district=district, name=a["name"],
                defaults={"name_bn": a.get("name_bn", ""), "group": a["group"], "group_bn": a.get("group_bn", "")})
            if not created and not obj.group:
                obj.group, obj.group_bn = a["group"], a.get("group_bn", "")
                obj.save(update_fields=["group", "group_bn"])


class Migration(migrations.Migration):
    dependencies = [("reference", "0003_area_groups")]
    operations = [migrations.RunPython(add_areas, migrations.RunPython.noop)]
