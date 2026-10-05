"""
Public interface of the Reference Data module.
Other modules call these functions; they never touch reference tables directly.
"""
from django.conf import settings
from django.contrib.postgres.search import TrigramSimilarity, TrigramWordSimilarity
from django.db import connection, transaction
from django.db.models import Case, FloatField, IntegerField, OuterRef, Q, Subquery, Value, When
from django.db.models.functions import Coalesce, Greatest
from django.utils import timezone

from apps.core import audit

from .models import District, School, SchoolAlias, Upazila
from .normalize import normalize_school_name


# ---- Locations ------------------------------------------------------------- #
def districts_with_regions():
    return District.objects.select_related("region").order_by("name")


def region_for_district(district):
    """Region is always read from the DB at call time — never cached in code."""
    return district.region if district.region_id and not district.region.is_deleted else None


def upazila_in_district(upazila_id, district_id):
    return Upazila.objects.filter(pk=upazila_id, district_id=district_id).first()


def sort_areas(upazilas):
    """A district's areas in list order: city-corporation thanas (by corporation), cantonments,
    upazilas, then "Other area". Templates group them with {% regroup … by group_label %}."""
    return sorted(upazilas, key=lambda u: u.sort_key)


def areas_of(district_id):
    return sort_areas(Upazila.objects.filter(district_id=district_id or 0))


@transaction.atomic
def assign_district_region(district, region, *, request):
    before = {"region": district.region.code if district.region_id else None}
    if district.region_id == (region.pk if region else None):
        return False
    district.region = region
    district.save(update_fields=["region", "updated_at"])
    audit.record("reference.district_region_changed", request=request, entity=district,
                 before=before, after={"region": region.code if region else None})
    return True


# ---- School search & resolution (roadmap §3.6) ----------------------------- #
def _alive_schools():
    return School.objects.filter(merged_into__isnull=True).exclude(verification_status=School.Status.MERGED)


# A school in the student's own area ranks this much higher than an equally good match elsewhere
# in the district (similarity is 0..1), so it comes first unless another name fits clearly better.
SAME_AREA_BONUS = 0.15


def search_schools(upazila_id=None, query="", limit=8, verified_only=False, *, district_id=None,
                   prefer_upazila_id=None):
    """Typeahead: fuzzy match on canonical names and aliases. Scoped to the district (the public form:
    a student may attend a school in another upazila / thana of their district; schools in
    `prefer_upazila_id` rank first) or, without `district_id`, to one upazila (dashboard lists).
    The public form passes verified_only=True so students are only offered approved schools;
    the dashboard editor also sees pending ones. Each school comes with its `upazila` (area)."""
    qs = _alive_schools().select_related("upazila")
    qs = qs.filter(district_id=district_id) if district_id else qs.filter(upazila_id=upazila_id)
    if verified_only:
        qs = qs.filter(verification_status=School.Status.VERIFIED)
    prefer = prefer_upazila_id or 0
    same_area = Case(When(upazila_id=prefer, then=Value(1)), default=Value(0), output_field=IntegerField())
    qn = normalize_school_name(query)
    if not qn:  # 'verified' > 'pending'
        return list(qs.annotate(same=same_area).order_by("-same", "-verification_status", "name")[:limit])
    alias_score = (
        SchoolAlias.objects.filter(school=OuterRef("pk"))
        .annotate(s=TrigramWordSimilarity(Value(qn), "alias_normalized"))
        .order_by("-s").values("s")[:1]
    )
    return list(
        qs.annotate(
            s_name=TrigramWordSimilarity(Value(qn), "name_normalized"),
            s_alias=Coalesce(Subquery(alias_score, output_field=FloatField()), Value(0.0)),
        )
        .annotate(score=Greatest("s_name", "s_alias"),
                  rank=Greatest("s_name", "s_alias") + Case(When(upazila_id=prefer, then=Value(SAME_AREA_BONUS)),
                                                            default=Value(0.0), output_field=FloatField()))
        .filter(Q(score__gte=0.3) | Q(name_normalized__contains=qn))
        .order_by("-rank", "name")[:limit]
    )


def resolve_school(*, upazila, typed_text, school_id=None):
    """
    Returns (school, how). how ∈ {'selected', 'exact', 'alias', 'auto', 'created'}.
    Never returns a merged school: references are redirected to the canonical one.
    """
    # A school picked from the suggestions may be anywhere in the student's district (they can attend
    # a school outside their own upazila / thana). A typed name is only matched within the chosen
    # area: common names ("Government Girls High School") exist in many upazilas.
    if school_id:
        school = School.objects.filter(pk=school_id, district_id=upazila.district_id).first()
        if school:
            return school.canonical(), "selected"

    qn = normalize_school_name(typed_text)
    if not qn:
        raise ValueError("School name is empty")

    exact = _alive_schools().filter(upazila=upazila, name_normalized=qn).first()
    if exact:
        return exact, "exact"
    alias = (SchoolAlias.objects.select_related("school")
             .filter(school__upazila=upazila, school__is_deleted=False, alias_normalized=qn).first())
    if alias:
        return alias.school.canonical(), "alias"

    threshold = settings.WIKISCHOLAR["SCHOOL_AUTO_RESOLVE_THRESHOLD"]
    best = (_alive_schools().filter(upazila=upazila)
            .annotate(sim=TrigramSimilarity("name_normalized", Value(qn)))
            .filter(sim__gte=threshold).order_by("-sim").first())
    if best:
        return best, "auto"

    school = School.objects.create(
        name=typed_text.strip(), upazila=upazila, district_id=upazila.district_id,
        verification_status=School.Status.PENDING, source=School.Source.REGISTRATION,
    )
    return school, "created"


# ---- Adding & removing schools (dashboard) ------------------------------- #
def same_name_school(upazila, name):
    """A live school in the upazila whose name or an alias is `name` once normalised, else None."""
    qn = normalize_school_name(name)
    school = _alive_schools().filter(upazila=upazila, name_normalized=qn).first()
    if school:
        return school
    alias = (SchoolAlias.objects.select_related("school")
             .filter(school__upazila=upazila, school__is_deleted=False, alias_normalized=qn).first())
    return alias.school.canonical() if alias else None


def similar_schools(upazila, name, limit=8):
    """Live schools in the upazila whose name or an alias is as close to `name` as the duplicate
    review would flag (SCHOOL_DUPLICATE_THRESHOLD), closest first."""
    qn = normalize_school_name(name)
    alias_score = (SchoolAlias.objects.filter(school=OuterRef("pk"))
                   .annotate(s=TrigramSimilarity("alias_normalized", Value(qn))).order_by("-s").values("s")[:1])
    return list(
        _alive_schools().filter(upazila=upazila)
        .annotate(score=Greatest(TrigramSimilarity("name_normalized", Value(qn)),
                                 Coalesce(Subquery(alias_score, output_field=FloatField()), Value(0.0))))
        .filter(score__gte=settings.WIKISCHOLAR["SCHOOL_DUPLICATE_THRESHOLD"])
        .order_by("-score", "name")[:limit]
    )


@transaction.atomic
def add_school(*, upazila, name, request):
    school = School.objects.create(
        name=name, upazila=upazila, district_id=upazila.district_id, verification_status=School.Status.VERIFIED,
        source=School.Source.ADMIN, verified_by=request.user, verified_at=timezone.now())
    audit.record("school.created", request=request, entity=school, after=audit.snapshot(school))
    return school


def removal_blocker(school):
    """Why `school` can't be removed yet, or "" if it can."""
    n = school.students.count()
    if n:
        return (f"{n} student{'s are' if n != 1 else ' is'} linked to this school. If it is a duplicate, "
                "merge it into the right school from Review duplicates instead.")
    if school.merged_from.exists():
        return "Other schools were merged into this one, so it can't be removed."
    return ""


@transaction.atomic
def remove_school(school, *, request, reason=""):
    if blocker := removal_blocker(school):
        raise ValueError(blocker)
    school.soft_delete(by=request.user)
    audit.record("school.removed", request=request, entity=school, meta={"reason": reason})


@transaction.atomic
def restore_school(school, *, request):
    clash = same_name_school(school.upazila, school.name)
    if clash:
        raise ValueError(f"“{clash.name}” is already listed in {school.upazila.name}, so this can't be restored.")
    school.restore()
    audit.record("school.restored", request=request, entity=school)


# ---- Duplicate review & merge --------------------------------------------- #
def find_duplicate_pairs(district_id=None, threshold=None, limit=200):
    threshold = threshold or settings.WIKISCHOLAR["SCHOOL_DUPLICATE_THRESHOLD"]
    sql = """
        SELECT a.id, b.id, similarity(a.name_normalized, b.name_normalized) AS sim
        FROM schools a
        JOIN schools b ON a.upazila_id = b.upazila_id AND a.id < b.id
        WHERE a.is_deleted = FALSE AND b.is_deleted = FALSE
          AND a.merged_into_id IS NULL AND b.merged_into_id IS NULL
          AND a.name_normalized %% b.name_normalized
          AND similarity(a.name_normalized, b.name_normalized) >= %s
          {district_clause}
        ORDER BY sim DESC
        LIMIT %s
    """.format(district_clause="AND a.district_id = %s" if district_id else "")
    params = [threshold] + ([district_id] if district_id else []) + [limit]
    with transaction.atomic(), connection.cursor() as cur:
        cur.execute("SET LOCAL pg_trgm.similarity_threshold = %s", [min(threshold, 0.3)])
        cur.execute(sql, params)
        rows = cur.fetchall()
    ids = {i for r in rows for i in r[:2]}
    schools = School.objects.select_related("upazila", "district").in_bulk(ids)
    return [(schools[a], schools[b], round(sim, 2)) for a, b, sim in rows if a in schools and b in schools]


@transaction.atomic
def merge_schools(*, keep, duplicate, request):
    """
    Redirect `duplicate` into `keep`. Students are re-pointed (with edit history),
    aliases move over, the duplicate's name becomes an alias, and the duplicate
    row stays in the table with status=merged. Nothing is deleted.
    """
    from apps.registration.services import reassign_school  # registration owns students

    keep = School.objects.select_for_update().get(pk=keep.pk)
    duplicate = School.objects.select_for_update().get(pk=duplicate.pk)
    if keep.pk == duplicate.pk:
        raise ValueError("Cannot merge a school into itself.")
    if keep.upazila_id != duplicate.upazila_id:
        raise ValueError("Schools can only be merged within the same upazila.")
    if duplicate.merged_into_id or keep.merged_into_id:
        raise ValueError("One of these schools has already been merged.")

    before = audit.snapshot(duplicate)
    moved_students = reassign_school(from_school=duplicate, to_school=keep, request=request,
                                     reason=f"School merge #{duplicate.pk} → #{keep.pk}")
    moved_aliases = list(SchoolAlias.objects.filter(school=duplicate).values_list("pk", flat=True))
    for alias in SchoolAlias.objects.filter(school=duplicate):
        if SchoolAlias.objects.filter(school=keep, alias_normalized=alias.alias_normalized).exists():
            continue
        alias.school = keep
        alias.save(update_fields=["school", "updated_at"])
    if duplicate.name_normalized != keep.name_normalized and not SchoolAlias.objects.filter(
            school=keep, alias_normalized=duplicate.name_normalized).exists():
        SchoolAlias.objects.create(school=keep, alias_text=duplicate.name, source=SchoolAlias.Source.MERGE,
                                   created_by=request.user)
    duplicate.merged_into = keep
    duplicate.verification_status = School.Status.MERGED
    duplicate.save(update_fields=["merged_into", "verification_status", "updated_at"])
    audit.record("school.merged", request=request, entity=duplicate, before=before,
                 after=audit.snapshot(duplicate),
                 meta={"kept_school_id": keep.pk, "students_moved": moved_students, "aliases_moved": moved_aliases})
    return len(moved_students)


@transaction.atomic
def set_school_status(school, status, *, request):
    before = audit.snapshot(school)
    school.verification_status = status
    if status == School.Status.VERIFIED:
        school.verified_by, school.verified_at = request.user, timezone.now()
    school.save()
    audit.record("school.status_changed", request=request, entity=school, before=before, after=audit.snapshot(school))


@transaction.atomic
def rename_school(school, new_name, *, request):
    before = audit.snapshot(school)
    old = school.name
    school.name = new_name
    school.save()
    if normalize_school_name(old) != school.name_normalized:
        SchoolAlias.objects.get_or_create(
            school=school, alias_normalized=normalize_school_name(old),
            defaults={"alias_text": old, "source": SchoolAlias.Source.RENAME, "created_by": request.user})
    audit.record("school.renamed", request=request, entity=school, before=before, after=audit.snapshot(school))


def add_alias(school, text, *, request):
    alias, created = SchoolAlias.objects.get_or_create(
        school=school, alias_normalized=normalize_school_name(text),
        defaults={"alias_text": text.strip(), "source": SchoolAlias.Source.ADMIN, "created_by": request.user})
    if created:
        audit.record("school.alias_added", request=request, entity=school, after={"alias": alias.alias_text})
    return alias
