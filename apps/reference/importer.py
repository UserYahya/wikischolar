"""Bulk school import from CSV (dashboard Schools → Import, and `manage.py import_schools`).

The CSV has district, upazila and name columns. `plan()` checks every row without saving and
says what would happen to it; `apply()` creates the rows that are new (plus any similar-name rows
the admin chose to add), re-checking first because the data may have changed in between.
"""
import csv
import io

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.core import audit
from apps.core.utils import english_text

from . import services
from .models import District, School, Upazila
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


TEMPLATE_HEADER = ["District", "Upazila / Area", "School name"]
# The area column may be headed "Upazila / Area" (template), "Upazila" (older templates) or "Area".
AREA_COLUMNS = ("upazila / area", "upazila/area", "upazila", "area", "thana")


def _csv(rows):
    out = io.StringIO()
    out.write("\ufeff")  # BOM so Excel opens it as UTF-8
    csv.writer(out).writerows(rows)
    return out.getvalue()


def template_csv():
    """The file admins fill in and upload: just the column headings."""
    return _csv([TEMPLATE_HEADER])


def locations_csv(district=None):
    """Reference list of every upazila and area (city-corporation thanas, cantonments, "Other area";
    all, or one district's) with its district, in English and Bangla, so the template can be filled in
    with the spellings the import recognises."""
    upazilas = Upazila.objects.select_related("district")
    if district:
        upazilas = upazilas.filter(district=district)
    upazilas = sorted(upazilas, key=lambda u: (u.district.name.casefold(), u.sort_key))
    return _csv([["District", "Upazila / Area", "Group", "District (Bangla)", "Upazila / Area (Bangla)"]]
                + [[u.district.name, u.name, u.group_label, u.district.name_bn, u.name_bn] for u in upazilas])


def read_rows(data):
    """Bytes of a CSV file → list of {"line", "district", "upazila", "name"}; blank-name rows are dropped."""
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
    if di is None or ui is None:
        raise ImportFileError("The first row must be the column headings: District, Upazila / Area, School name. "
                              "Download the template to start from the right layout.")
    ni = next((header.index(c) for c in NAME_COLUMNS if c in header), None)
    if ni is None:
        raise ImportFileError("There is no “School name” column.")
    rows = []
    for line, cells in enumerate(reader, start=2):
        cell = lambda i: cells[i].strip() if i < len(cells) else ""  # noqa: E731
        if not cell(ni):
            continue
        rows.append({"line": line, "district": cell(di), "upazila": cell(ui), "name": cell(ni)})
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
    upazilas = {(u.district_id, _key(n)): u for u in Upazila.objects.all() for n in (u.name, u.name_bn) if _key(n)}
    seen = {}
    out = []
    for raw in rows:
        row = dict(raw)
        out.append(row)
        district = districts.get(_key(row["district"]))
        if not district:
            row.update(result=ERROR, message=f"Unknown district “{row['district']}”." if row["district"]
                       else "The district is missing.")
            continue
        upz = upazilas.get((district.pk, _key(row["upazila"])))
        if not upz:
            row.update(result=ERROR, message=f"No upazila or area “{row['upazila']}” in {district.name}."
                       if row["upazila"] else "The upazila / area is missing.")
            continue
        row.update(district=district.name, upazila=upz.name, upazila_id=upz.pk)
        try:
            row["name"] = english_text(row["name"])
        except ValidationError as exc:
            row.update(result=ERROR, message=exc.messages[0])
            continue
        if len(row["name"]) > 255:
            row.update(result=ERROR, message="The name is longer than 255 characters.")
            continue
        key = (upz.pk, normalize_school_name(row["name"]))
        if key in seen:
            row.update(result=REPEATED, message=f"Same school as row {seen[key]}.")
            continue
        seen[key] = row["line"]
        if same := services.same_name_school(upz, row["name"]):
            row.update(result=EXISTS, school=same)
        elif similar := services.similar_schools(upz, row["name"], limit=3):
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
    upazilas = Upazila.objects.in_bulk({r["upazila_id"] for r in planned if r.get("upazila_id")})
    user = actor or (request.user if request else None)
    verified = status == School.Status.VERIFIED
    created = []
    for r in planned:
        if r["result"] == NEW or (r["result"] == SIMILAR and r["line"] in add_similar):
            upz = upazilas[r["upazila_id"]]
            created.append(School.objects.create(
                name=r["name"], upazila=upz, district_id=upz.district_id, verification_status=status,
                source=School.Source.IMPORT, verified_by=user if verified else None,
                verified_at=timezone.now() if verified else None))
    if created:
        audit.record("school.imported", request=request, actor=actor,
                     meta={"created": len(created), "status": status, "ids": [s.pk for s in created]})
    return created, planned

