import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.reference.models import District, Region, Thana


class Command(BaseCommand):
    help = ("Seed regions, districts and thanas (with cantonments and \"Other thana\") from a JSON file. "
            "Idempotent. "
            "It only adds what is missing: names of existing regions and districts (renamed in the "
            "dashboard) are never overwritten, and district→region assignments are kept "
            "unless --reset-region-assignments is given.")

    def add_arguments(self, parser):
        parser.add_argument("--file", default=str(Path(settings.BASE_DIR) / "data" / "reference_seed.json"))
        parser.add_argument("--reset-region-assignments", action="store_true")
        parser.add_argument("--if-empty", action="store_true",
                            help="Do nothing when regions already exist (run on every container start).")

    @transaction.atomic
    def handle(self, file, reset_region_assignments, if_empty=False, **opts):
        if if_empty and Region.all_objects.exists():
            self.stdout.write("Reference data already loaded; nothing to do (--if-empty).")
            return
        data = json.loads(Path(file).read_text(encoding="utf-8"))
        regions = {}
        for i, r in enumerate(data["regions"]):
            # get_or_create: a region renamed in the dashboard keeps its name
            obj, _ = Region.all_objects.get_or_create(
                code=r["code"], defaults={"name": r["name"], "name_bn": r.get("name_bn", ""), "sort_order": i})
            regions[r["code"]] = obj
        new_d = new_t = kept = 0
        for d in data["districts"]:
            district = District.all_objects.filter(code=d["code"]).first()
            seed_region = regions.get(d.get("region"))
            if district is None:
                district = District.all_objects.create(code=d["code"], name=d["name"],
                                                       name_bn=d.get("name_bn", ""), region=seed_region)
                new_d += 1
            else:  # an existing district keeps its name
                if reset_region_assignments or district.region_id is None:
                    district.region = seed_region
                elif district.region_id != (seed_region.pk if seed_region else None):
                    kept += 1
                district.save()
            for t in d.get("thanas", []):
                obj, created = Thana.all_objects.get_or_create(
                    district=district, name=t["name"],
                    defaults={"name_bn": t.get("name_bn", ""), "group": t.get("group", ""),
                              "group_bn": t.get("group_bn", "")})
                if not created and t.get("group") and not obj.group:  # an older copy without its group: add it
                    obj.group, obj.group_bn = t["group"], t.get("group_bn", "")
                    obj.save(update_fields=["group", "group_bn"])
                new_t += created
        self.stdout.write(self.style.SUCCESS(
            f"Seeded {len(regions)} regions, {new_d} new districts, {new_t} new thanas (with cantonments and "
            f"\"Other thana\"). {kept} dashboard region assignments preserved."))
