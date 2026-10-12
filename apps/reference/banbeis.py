"""Load the government's school list (BANBEIS institution list, e-survey 2024) into `schools`.

`manage.py import_banbeis_schools FILE.xlsx [--dry-run]`. Each row has EIIN, institute name,
district, thana and the government data (education level, management, MPO, …). Rows are matched in
this order:
  1. a school with the same EIIN: its government data (and name) are updated;
  2. a live school without an EIIN with the same normalised name in that thana (or, if it has no
     thana, in that district): it gets the EIIN and data, keeping its id, so its students stay linked;
  3. otherwise a new verified school (source "BANBEIS list") is created.
Removed schools are never brought back. Thanas come from data/thana_mapping.csv (the sheet's thana
name -> our thana), so the sheet's spellings resolve exactly as when the thana list was built.
Running it again changes nothing.
"""
import csv
import re
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.core import audit

from .models import District, School, SchoolAlias, Thana
from .normalize import normalize_school_name
from .xlsx import read_table

# The sheet's district typos (same list as scripts/build_thana_seed.py).
DISTRICT_FIXES = {"Brahamanbaria": "Brahmanbaria", "Coxs Bazar": "Cox's Bazar", "Nawabganj": "Chapainawabganj"}
GOVERNMENT_FIELDS = ["division", "institute_type", "education_level", "management", "mpo", "institute_for",
                     "geographical_position", "area_status", "post_office", "email"]


def _key(text):
    return re.sub(r"[^a-z]", "", (text or "").casefold())


# Sheet value (letters only, lower case) -> our choice. The sheet's spellings vary ("CRISTIAN",
# "SEPERATE", "HAOR/BIL" and "HAOR/BILL"), hence the extra keys.
_CHOICES = {
    "institute_type": {"school": "school", "schoolcollege": "school_and_college", "schoolandcollege": "school_and_college",
                       "college": "college"},
    "education_level": {"secondary": "secondary", "juniorsecondary": "junior_secondary",
                        "govtprimarypretoeight": "primary_to_eight", "highersecondary": "higher_secondary",
                        "degreepass": "degree_pass", "degreehonors": "degree_honours", "degreehonours": "degree_honours",
                        "masters": "masters"},
    "management": {"government": "government", "nongovernment": "non_government",
                   "localgovernment": "local_government", "autonomous": "autonomous",
                   "cantonmentboard": "cantonment_board", "cristianmissionary": "christian_missionary",
                   "christianmissionary": "christian_missionary", "ngo": "ngo", "other": "other"},
    "mpo": {"yes": "yes", "no": "no", "notapplicable": "not_applicable"},
    "institute_for": {"coeducation": "co_education", "coeducationseperateshift": "co_education_separate_shift",
                      "coeducationseparateshift": "co_education_separate_shift", "girls": "girls", "boys": "boys"},
    "geographical_position": {
        "plainland": "plain_land", "riverside": "river_side", "hillyarea": "hilly_area",
        "coastalareainsideembankment": "coastal_inside", "coastalareaoutsideembankment": "coastal_outside",
        "haorbilinsideembankment": "haor_inside", "haorbillinsideembankment": "haor_inside",
        "haorbiloutsideembankment": "haor_outside", "haorbilloutsideembankment": "haor_outside",
        "teagarden": "tea_garden", "char": "char", "borderarea": "border_area",
        "industrialarea": "industrial_area", "islanddwip": "island", "salinearea": "saline_area",
        "waterlogged": "water_logged", "other": "other"},
    "area_status": {"rural": "rural", "citycorporation": "city_corporation",
                    "districtsadarpoura": "district_sadar_poura", "upazilasadarpoura": "upazila_sadar_poura",
                    "upazilasadarnotpoura": "upazila_sadar_not_poura", "otherpouraareas": "other_poura"},
}
_COLUMNS = {"institute_type": "INSTITUTE_TYPE_NAME", "education_level": "EDUCATION_LEVEL_NAME",
            "management": "MANAGEMENT_NAME", "mpo": "IS_MPO", "institute_for": "INSTITUTE_FOR_WHOM",
            "geographical_position": "GEOGRAPHICAL_POSITION_NAME", "area_status": "AREA_STATUS_NAME"}
_BLANK = {"", "none", "null", "na", "n/a"}


def _text(value):
    value = " ".join((value or "").split())
    return "" if value.casefold() in _BLANK else value


def government_data(row):
    """The sheet row's government fields as our values, plus the sheet values we didn't recognise."""
    data, unknown = {"division": _text(row.get("DIVISION_NAME")), "post_office": _text(row.get("POST_OFFICE_NAME"))}, []
    email = _text(row.get("EMAIL")).lower()
    data["email"] = email if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email) else ""
    for field, column in _COLUMNS.items():
        raw = _text(row.get(column))
        data[field] = _CHOICES[field].get(_key(raw), "") if raw else ""
        if raw and not data[field]:
            unknown.append(f"{column}={raw}")
    return data, unknown


def _thana_lookup():
    """(district code, the sheet's thana name) -> our thana name, from data/thana_mapping.csv."""
    path = Path(settings.BASE_DIR) / "data" / "thana_mapping.csv"
    with path.open(encoding="utf-8") as fh:
        return {(r["district_code"], r["sheet_name"]): r["thana"] for r in csv.DictReader(fh) if r["sheet_name"]}


class _Rollback(Exception):
    pass


def import_schools(path, *, dry_run=False, types=(), log=print):
    """Import the sheet; returns the counts (also written to one audit entry unless `dry_run`).
    `types`: import only rows whose INSTITUTE_TYPE_NAME is one of these (ignoring case), e.g.
    ("SCHOOL & COLLEGE",); the rest are counted as other_type. Empty: every row."""
    rows = read_table(path, "EIIN_NO")
    counts = dict(rows=len(rows), created=0, matched_by_name=0, updated=0, unchanged=0, unresolved=0,
                  unknown_values=0, other_type=0)
    if types:
        wanted = {_key(t) for t in types}
        kept = [r for r in rows if _key(r.get("INSTITUTE_TYPE_NAME")) in wanted]
        counts["other_type"] = len(rows) - len(kept)
        rows = kept
    try:
        with transaction.atomic():
            _import(rows, counts, log, types)
            if dry_run:
                raise _Rollback
    except _Rollback:
        log("Dry run: nothing was saved.")
    return counts


def _import(rows, counts, log, types=()):
    now = timezone.now()
    districts = {d.name: d for d in District.objects.all()}
    thanas = {(t.district_id, t.name): t for t in Thana.objects.all()}
    lookup = _thana_lookup()
    by_eiin = {s.eiin: s for s in School.all_objects.exclude(eiin="")}
    by_name = {}  # live schools without an EIIN, by where they are and their normalised name
    for s in School.objects.filter(eiin="").exclude(verification_status=School.Status.MERGED):
        by_name.setdefault((s.district_id, s.thana_id, s.name_normalized), s)
    new, changed, aliases, seen = [], {}, [], set()
    for row in rows:
        line = row["_row"]
        eiin = row.get("EIIN_NO", "")
        name = " ".join(row.get("INSTITUTE_NAME", "").split()).upper()
        raw_district = row.get("DISTRICT_NAME", "")
        district = districts.get(DISTRICT_FIXES.get(raw_district, raw_district))
        thana = None
        if district:
            thana = thanas.get((district.pk, lookup.get((district.code, row.get("THANA_NAME", "")), "")))
        if not re.fullmatch(r"[0-9]{6}", eiin) or not name or not district or not thana or eiin in seen:
            counts["unresolved"] += 1
            log(f"  Row {line}: skipped (EIIN {eiin or '-'}, {name or 'no name'}, "
                f"{raw_district or 'no district'} / {row.get('THANA_NAME') or 'no thana'})")
            continue
        seen.add(eiin)
        data, unknown = government_data(row)
        if unknown:
            counts["unknown_values"] += 1
            log(f"  Row {line}: unrecognised {', '.join(unknown)} (left blank)")
        normalized = normalize_school_name(name)
        school = by_eiin.get(eiin)
        if school is None:
            school = (by_name.pop((district.pk, thana.pk, normalized), None)
                      or by_name.pop((district.pk, None, normalized), None))
            if school is not None:
                counts["matched_by_name"] += 1
                school.eiin = eiin
                if school.verification_status != School.Status.VERIFIED:
                    school.verification_status, school.verified_at = School.Status.VERIFIED, now
                school.thana_id = school.thana_id or thana.pk
                changed[school.pk] = school
        if school is None:
            new.append(School(name=name, name_normalized=normalized, district=district, thana=thana, eiin=eiin,
                              verification_status=School.Status.VERIFIED, verified_at=now,
                              source=School.Source.GOVERNMENT, **data))
            continue
        if school.name != name:
            if school.name_normalized != normalized:
                aliases.append(SchoolAlias(school=school, alias_text=school.name,
                                           alias_normalized=school.name_normalized, source=SchoolAlias.Source.RENAME))
            school.name, school.name_normalized = name, normalized
            changed[school.pk] = school
        for field, value in data.items():
            if getattr(school, field) != value:
                setattr(school, field, value)
                changed[school.pk] = school
        if school.pk not in changed:
            counts["unchanged"] += 1
    counts["created"] = len(new)
    counts["updated"] = len(changed) - counts["matched_by_name"]
    School.objects.bulk_create(new, batch_size=1000)
    fields = ["name", "name_normalized", "eiin", "thana", "verification_status", "verified_at", "updated_at",
              *GOVERNMENT_FIELDS]
    for s in changed.values():
        s.updated_at = now
    School.all_objects.bulk_update(list(changed.values()), fields, batch_size=1000)
    existing = set(SchoolAlias.all_objects.filter(school__in=[a.school for a in aliases])
                   .values_list("school_id", "alias_normalized"))
    SchoolAlias.objects.bulk_create([a for a in aliases if (a.school_id, a.alias_normalized) not in existing],
                                    batch_size=1000)
    if new or changed:
        audit.record("school.government_import", actor_type="system", entity_type="schools",
                     meta=dict(counts, source="BANBEIS e-survey 2024", types=list(types)))
    log("  " + ", ".join(f"{k.replace('_', ' ')}: {v}" for k, v in counts.items()))
