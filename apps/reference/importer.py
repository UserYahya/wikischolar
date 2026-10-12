"""Bulk school import from CSV (dashboard Schools → Import, and `manage.py import_schools`).

The CSV has district, thana and name columns; the thana may be left blank (or the
column left out) when it isn't known: such a school belongs to its whole district until an admin sets
its thana. `plan()` checks every row without saving and
says what would happen to it; `apply()` creates the rows that are new (plus any similar-name rows
the admin chose to add), re-checking first because the data may have changed in between.
`undo()` removes (archives) the schools one import created (`manage.py undo_school_import`).
"""
import csv
import io

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.core import audit
from apps.core.utils import english_text

from . import services
from .models import District, School, Thana
from .normalize import normalize_school_name

MAX_ROWS = 2000
MAX_BYTES = 1024 * 1024
NAME_COLUMNS = ("name", "school", "school_name", "school name")

# Row outcomes
NEW, SIMILAR, EXISTS, REPEATED, ERROR = "new", "similar", "exists", "repeated", "error"


class ImportFileError(ValueError):
    """The file as a whole can't be read (wrong columns, too big, not CSV)."""


def _key(text):
    return " ".join((text or "").split()).casefold()


TEMPLATE_HEADER = ["District", "Thana", "School name"]
# The thana column is headed "Thana" (template); older templates said "Upazila / Area", "Upazila" or "Area".
AREA_COLUMNS = ("thana", "upazila / area", "upazila/area", "upazila", "area")


def _csv(rows):
    out = io.StringIO()
    out.write("\ufeff")  # BOM so Excel opens it as UTF-8
    csv.writer(out).writerows(rows)
    return out.getvalue()


def template_csv():
    """The file admins fill in and upload: just the column headings."""
    return _csv([TEMPLATE_HEADER])


def locations_csv(district=None):
    """Reference list of every thana (with cantonments and "Other thana"; all, or one district's) with its district, in English and Bangla, so the template can be filled in
    with the spellings the import recognises."""
    thanas = Thana.objects.select_related("district")
    if district:
        thanas = thanas.filter(district=district)
    thanas = sorted(thanas, key=lambda u: (u.district.name.casefold(), u.sort_key))
    return _csv([["District", "Thana", "Group", "District (Bangla)", "Thana (Bangla)"]]
                + [[u.district.name, u.name, u.group_label, u.district.name_bn, u.name_bn] for u in thanas])


def read_rows(data):
    """Bytes of a CSV file → list of {"line", "district", "thana", "name"}; blank-name rows are dropped."""
    if len(data) > MAX_BYTES:
        raise ImportFileError("The file is larger than 1 MB. Split it into smaller files.")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("cp1252", errors="replace")  # Excel "CSV" on Windows
    reader = csv.reader(io.StringIO(text))
    header = [_key(h) for h in next(reader, [])]
    di = header.index("district") if "district" in header else None
    ui = next((header.index(c) for c in AREA_COLUMNS if c in header), None)
    if di is None:  # the Thana column is optional
        raise ImportFileError("The first row must be the column headings: District, Thana, School name "
                              "(Thana may be left blank). Download the template to start from the right "
                              "layout.")
    ni = next((header.index(c) for c in NAME_COLUMNS if c in header), None)
    if ni is None:
        raise ImportFileError("There is no “School name” column.")
    rows = []
    for line, cells in enumerate(reader, start=2):
        cell = lambda i: cells[i].strip() if i < len(cells) else ""  # noqa: E731
        if not cell(ni):
            continue
        rows.append({"line": line, "district": cell(di), "thana": cell(ui) if ui is not None else "",
                     "name": cell(ni)})
        if len(rows) > MAX_ROWS:
            raise ImportFileError(f"The file has more than {MAX_ROWS} schools. Split it into smaller files.")
    if not rows:
        raise ImportFileError("No school names found. Fill in the name column, one school per row.")
    return rows


def plan(rows):
    """Annotate each row with "result" (one of the outcomes above) and, where useful, "message",
    "school" (an existing School) or "similar" (a list of Schools). Nothing is saved."""
    # Matched by English or Bangla name, ignoring case and extra spaces.
    districts = {_key(n): d for d in District.objects.all() for n in (d.name, d.name_bn) if _key(n)}
    thanas = {(u.district_id, _key(n)): u for u in Thana.objects.all() for n in (u.name, u.name_bn) if _key(n)}
    seen_in_area, seen_in_district, seen_without_area = {}, {}, {}  # → row line
    out = []
    for raw in rows:
        row = dict(raw)
        out.append(row)
        district = districts.get(_key(row["district"]))
        if not district:
            row.update(result=ERROR, message=f"Unknown district “{row['district']}”." if row["district"]
                       else "The district is missing.")
            continue
        th = None
        if row["thana"]:  # blank = thana not known: the school belongs to the whole district
            th = thanas.get((district.pk, _key(row["thana"])))
            if not th:
                row.update(result=ERROR, message=f"No thana “{row['thana']}” in {district.name}. "
                                                 "Check the spelling, or leave it blank if you don't know it.")
                continue
        row.update(district=district.name, district_id=district.pk,
                   thana=th.name if th else "", thana_id=th.pk if th else None)
        try:
            row["name"] = english_text(row["name"])
        except ValidationError as exc:
            row.update(result=ERROR, message=exc.messages[0])
            continue
        if len(row["name"]) > 255:
            row.update(result=ERROR, message="The name is longer than 255 characters.")
            continue
        # A row without an area repeats any earlier row of the same name in the district; a row with
        # an area repeats one in the same area or one without an area.
        name_key = normalize_school_name(row["name"])
        if th:
            earlier = seen_in_area.get((th.pk, name_key)) or seen_without_area.get((district.pk, name_key))
        else:
            earlier = seen_in_district.get((district.pk, name_key))
        if earlier:
            row.update(result=REPEATED, message=f"Same school as row {earlier}.")
            continue
        seen_in_district.setdefault((district.pk, name_key), row["line"])
        if th:
            seen_in_area[(th.pk, name_key)] = row["line"]
        else:
            seen_without_area[(district.pk, name_key)] = row["line"]
        if same := services.same_name_school(th, row["name"], district_id=district.pk):
            row.update(result=EXISTS, school=same)
        elif similar := services.similar_schools(th, row["name"], limit=3, district_id=district.pk):
            row.update(result=SIMILAR, similar=similar)
        else:
            row["result"] = NEW
    return out


def summary(planned):
    counts = {k: 0 for k in (NEW, SIMILAR, EXISTS, REPEATED, ERROR)}
    for r in planned:
        counts[r["result"]] += 1
    return counts


@transaction.atomic
def apply(rows, *, status=School.Status.VERIFIED, add_similar=(), request=None, actor=None):
    """Create the new rows, and similar-name rows whose line is in `add_similar`.
    Returns (created schools, re-checked plan)."""
    planned = plan(rows)
    thanas = Thana.objects.in_bulk({r["thana_id"] for r in planned if r.get("thana_id")})
    user = actor or (request.user if request else None)
    verified = status == School.Status.VERIFIED
    created = []
    for r in planned:
        if r["result"] == NEW or (r["result"] == SIMILAR and r["line"] in add_similar):
            created.append(School.objects.create(
                name=r["name"], thana=thanas.get(r["thana_id"]), district_id=r["district_id"],
                verification_status=status,
                source=School.Source.IMPORT, verified_by=user if verified else None,
                verified_at=timezone.now() if verified else None))
    if created:
        audit.record("school.imported", request=request, actor=actor,
                     meta={"created": len(created), "status": status, "ids": [s.pk for s in created]})
    return created, planned


@transaction.atomic
def undo(entry, *, dry_run=False):
    """Remove (archive, like a school page's *Remove school*) the schools created by the import
    logged as `entry`, a "school.imported" AuditLog row. Schools in use, or no longer imports, are
    kept. Returns (removed schools, {kept school: reason}, ids already removed). Removed schools are
    left out of the list, suggestions and duplicate checks, and can be restored from Schools → Removed."""
    ids = entry.meta.get("ids") or []
    schools = School.all_objects.select_related("thana", "district").in_bulk(ids)
    gone = [i for i in ids if i not in schools or schools[i].is_deleted]
    removed, kept = [], {}
    for school in (s for s in schools.values() if not s.is_deleted):
        if school.source != School.Source.IMPORT:
            reason = "it is no longer marked as imported"
        elif school.merged_into_id:
            reason = f"it was merged into #{school.merged_into_id}"
        else:
            reason = services.removal_blocker(school)
        if reason:
            kept[school] = reason
        else:
            removed.append(school)
    if removed and not dry_run:
        pks = [s.pk for s in removed]
        School.all_objects.filter(pk__in=pks).soft_delete()
        audit.record("school.import_undone", actor_type="system", entity_type="audit_logs", entity_id=entry.pk,
                     meta={"removed": len(pks), "ids": pks, "kept": {str(s.pk): r for s, r in kept.items()},
                           "already_removed": gone})
    return removed, kept, gone
