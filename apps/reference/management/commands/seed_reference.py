import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.reference.models import District, Region, Upazila


class Command(BaseCommand):
    help = ("Seed regions, districts and upazilas from a JSON file. Idempotent. "
            "Existing district→region assignments (edited in the dashboard) are kept "
            "unless --reset-region-assignments is given.")

    def add_arguments(self, parser):
        parser.add_argument("--file", default=str(Path(settings.BASE_DIR) / "data" / "reference_seed.json"))
        parser.add_argument("--reset-region-assignments", action="store_true")

    @transaction.atomic
    def handle(self, file, reset_region_assignments, **opts):
        data = json.loads(Path(file).read_text(encoding="utf-8"))
        regions = {}
        for i, r in enumerate(data["regions"]):
            obj, _ = Region.all_objects.update_or_create(
                code=r["code"], defaults={"name": r["name"], "name_bn": r.get("name_bn", ""), "sort_order": i})
            regions[r["code"]] = obj
        new_d = new_u = kept = 0
        for d in data["districts"]:
            district = District.all_objects.filter(code=d["code"]).first()
            seed_region = regions.get(d.get("region"))
            if district is None:
                district = District.all_objects.create(code=d["code"], name=d["name"],
                                                       name_bn=d.get("name_bn", ""), region=seed_region)
                new_d += 1
            else:
                district.name, district.name_bn = d["name"], d.get("name_bn", "")
                if reset_region_assignments or district.region_id is None:
                    district.region = seed_region
                elif district.region_id != (seed_region.pk if seed_region else None):
                    kept += 1
                district.save()
            for u in d.get("upazilas", []):
                _, created = Upazila.all_objects.get_or_create(
                    district=district, name=u["name"], defaults={"name_bn": u.get("name_bn", "")})
                new_u += created
        self.stdout.write(self.style.SUCCESS(
            f"Seeded {len(regions)} regions, {new_d} new districts, {new_u} new upazilas. "
            f"{kept} dashboard region assignments preserved."))
