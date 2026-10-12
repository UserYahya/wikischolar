"""Swap an existing database over to the government district and thana lists (migration
reference.0007), from data/reference_seed.json and the reviewed data/thana_mapping.csv.

Per district (matched by `code`): the district takes the government name; each thana in the new list
re-uses the row it replaces (renamed in place, so students and schools keep pointing at it) or a
row that already has its name, or is created. Every other row of the district is retired: its
students and schools move to the thana the mapping names (the district's "Other thana" if none) and
the row is archived. Nothing is deleted (the database refuses hard deletes).

Works with real models and with a migration's historical models (whose plain manager sees archived
rows too), so it can be tested directly.
"""
import csv
import json
from collections import defaultdict
from pathlib import Path

from django.conf import settings
from django.utils import timezone

OTHER_GROUP = "Other"


def _all(model):
    """Every row, archived ones included: `all_objects` on real models, the plain manager in migrations."""
    return getattr(model, "all_objects", None) or model._default_manager


def load(base_dir=None):
    base = Path(base_dir or settings.BASE_DIR) / "data"
    seed = json.loads((base / "reference_seed.json").read_text(encoding="utf-8"))
    mapping = list(csv.DictReader((base / "thana_mapping.csv").open(encoding="utf-8")))
    return seed, mapping


def apply(*, District, Thana, School, Student, AuditLog, seed, mapping, log=print):
    """Apply the lists; returns the counts written to the audit entry."""
    now = timezone.now()
    retire_to = defaultdict(dict)  # district code -> {old name: new thana name}
    for r in mapping:
        if r["source"] == "retired":
            retire_to[r["district_code"]][r["replaces"]] = r["thana"]
    replaces = defaultdict(dict)  # district code -> {new thana name: old name it replaces}
    for r in mapping:
        if r["source"] != "retired" and r["replaces"]:
            replaces[r["district_code"]][r["thana"]] = r["replaces"]

    counts = dict(districts_renamed=0, thanas_renamed=0, thanas_created=0, thanas_restored=0,
                  thanas_retired=0, students_moved=0, schools_moved=0)
    retired_names = []
    districts = {d.code: d for d in _all(District).all()}
    if not districts:  # a new install: seed_reference loads the new lists
        return counts
    for d in seed["districts"]:
        district = districts.get(d["code"])
        if district is None:  # not seeded yet: seed_reference will add it with its thanas
            continue
        if district.name != d["name"]:
            log(f"  District {district.name} -> {d['name']}")
            district.name = d["name"]
            district.save(update_fields=["name", "updated_at"])
            counts["districts_renamed"] += 1
        rows = list(_all(Thana).filter(district=district))
        by_name = {t.name: t for t in rows}
        claimed = {}  # new name -> row
        # A row that already has the new name wins; then the row it replaces is renamed; else a new row.
        pending = []
        for t in d["thanas"]:
            row = by_name.get(t["name"])
            if row is not None:
                claimed[t["name"]] = row
            else:
                pending.append(t)
        for t in pending:
            old = by_name.get(replaces[d["code"]].get(t["name"], ""))
            if old is not None and old.pk not in {r.pk for r in claimed.values()}:
                old.name = t["name"]
                claimed[t["name"]] = old
                counts["thanas_renamed"] += 1
            else:
                claimed[t["name"]] = Thana(district=district, name=t["name"])
                counts["thanas_created"] += 1
        for t in d["thanas"]:
            row = claimed[t["name"]]
            row.name_bn, row.group, row.group_bn = t.get("name_bn", ""), t.get("group", ""), t.get("group_bn", "")
            if row.pk and row.is_deleted:
                row.is_deleted, row.deleted_at, row.deleted_by = False, None, None
                counts["thanas_restored"] += 1
            row.save()
        keep = {row.pk for row in claimed.values()}
        other = next(row for row in claimed.values() if row.group == OTHER_GROUP)
        for row in rows:
            if row.pk in keep:
                continue
            target = claimed.get(retire_to[d["code"]].get(row.name, ""), other)
            moved = _all(Student).filter(thana_id=row.pk).update(thana_id=target.pk)
            schools = _all(School).filter(thana_id=row.pk).update(thana_id=target.pk)
            counts["students_moved"] += moved
            counts["schools_moved"] += schools
            if not row.is_deleted:
                row.is_deleted, row.deleted_at = True, now
                row.save(update_fields=["is_deleted", "deleted_at", "updated_at"])
                counts["thanas_retired"] += 1
            retired_names.append(f"{d['name']}: {row.name} -> {target.name}")
            if moved or schools:
                log(f"  {d['name']}: {row.name} -> {target.name} ({moved} students, {schools} schools)")
    AuditLog.objects.create(actor_type="system", actor_label="system", action="reference.thanas_replaced",
                            entity_type="thanas", meta=dict(counts, retired=retired_names,
                                                            source="BANBEIS e-survey 2024"))
    log("  " + ", ".join(f"{k.replace('_', ' ')}: {v}" for k, v in counts.items()))
    return counts
