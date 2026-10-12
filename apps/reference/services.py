"""
Public interface of the Reference Data module.
Other modules call these functions; they never touch reference tables directly.
"""
import re

from django.conf import settings
from django.contrib.postgres.search import TrigramSimilarity, TrigramWordSimilarity
from django.db import connection, transaction
from django.db.models import Case, F, FloatField, IntegerField, OuterRef, Q, Subquery, Value, When
from django.db.models.functions import Coalesce, Greatest
from django.utils import timezone

from apps.core import audit

from .models import District, School, SchoolAlias, Thana
from .normalize import normalize_school_name


# ---- Locations ------------------------------------------------------------- #
def districts_with_regions():
    return District.objects.select_related("region").order_by("name")


def region_for_district(district):
    """Region is always read from the DB at call time — never cached in code."""
    return district.region if district.region_id and not district.region.is_deleted else None


def thana_in_district(thana_id, district_id):
    return Thana.objects.filter(pk=thana_id, district_id=district_id).first()


def sort_areas(thanas):
    """A district's thanas in list order: grouped thanas (if any), cantonments, thanas, then
    "Other thana". Templates group them with {% regroup … by group_label %}."""
    return sorted(thanas, key=lambda u: u.sort_key)


def areas_of(district_id):
    return sort_areas(Thana.objects.filter(district_id=district_id or 0))


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


def school_scope(thana=None, district_id=None, prefix=""):
    """Where a school at this location may already be listed (a Q on School, or on `prefix`school__...):
    the area itself plus its district's schools whose area isn't known yet; with no area, the whole
    district. A school without an area belongs to its whole district, so it is matched from every area."""
    if thana is not None:
        return (Q(**{f"{prefix}thana": thana})
                | Q(**{f"{prefix}thana__isnull": True, f"{prefix}district_id": thana.district_id}))
    return Q(**{f"{prefix}district_id": district_id})


# A school in the student's own area ranks this much higher than an equally good match elsewhere
# in the district (similarity is 0..1), so it comes first unless another name fits clearly better.
SAME_AREA_BONUS = 0.15


def search_schools(thana_id=None, query="", limit=8, verified_only=False, *, district_id=None,
                   prefer_thana_id=None):
    """Typeahead: fuzzy match on canonical names and aliases. Scoped to the district (the public form:
    a student may attend a school in another thana / thana of their district; schools in
    `prefer_thana_id` rank first) or, without `district_id`, to one thana plus its district's
    schools whose area isn't known (dashboard lists).
    The public form passes verified_only=True so students are only offered approved schools;
    the dashboard editor also sees pending ones. Each school comes with its `thana` (area)."""
    qs = _alive_schools().select_related("thana")
    if district_id:
        qs = qs.filter(district_id=district_id)
    else:
        thana_district = Thana.objects.filter(pk=thana_id or 0).values("district_id")[:1]
        qs = qs.filter(Q(thana_id=thana_id) | Q(thana__isnull=True, district_id=Subquery(thana_district)))
    if verified_only:
        qs = qs.filter(verification_status=School.Status.VERIFIED)
    if re.fullmatch(r"\s*[0-9]{6}\s*", query or ""):  # an EIIN: that school only
        return list(qs.filter(eiin=query.strip())[:limit])
    prefer = prefer_thana_id or 0
    same_area = Case(When(thana_id=prefer, then=Value(1)), default=Value(0), output_field=IntegerField())
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
                  rank=Greatest("s_name", "s_alias") + Case(When(thana_id=prefer, then=Value(SAME_AREA_BONUS)),
                                                            default=Value(0.0), output_field=FloatField()))
        .filter(Q(score__gte=0.3) | Q(name_normalized__contains=qn))
        .order_by("-rank", "name")[:limit]
    )


def resolve_school(*, thana, typed_text, school_id=None):
    """
    Returns (school, how). how ∈ {'selected', 'exact', 'alias', 'auto', 'created'}.
    Never returns a merged school: references are redirected to the canonical one.
    """
    # A school picked from the suggestions may be anywhere in the student's district (they can attend
    # a school outside their own thana / thana). A typed name is only matched within the chosen
    # area (or among the district's schools whose area isn't known): common names ("Government Girls
    # High School") exist in many thanas.
    if school_id:
        school = School.objects.filter(pk=school_id, district_id=thana.district_id).first()
        if school:
            return school.canonical(), "selected"

    qn = normalize_school_name(typed_text)
    if not qn:
        raise ValueError("School name is empty")

    scope = school_scope(thana)
    exact = (_alive_schools().filter(scope, name_normalized=qn)
             .order_by(F("thana_id").asc(nulls_last=True)).first())  # the student's own area first
    if exact:
        return exact, "exact"
    alias = (SchoolAlias.objects.select_related("school")
             .filter(school_scope(thana, prefix="school__"), school__is_deleted=False, alias_normalized=qn).first())
    if alias:
        return alias.school.canonical(), "alias"

    threshold = settings.WIKISCHOLAR["SCHOOL_AUTO_RESOLVE_THRESHOLD"]
    best = (_alive_schools().filter(scope)
            .annotate(sim=TrigramSimilarity("name_normalized", Value(qn)))
            .filter(sim__gte=threshold).order_by("-sim").first())
    if best:
        return best, "auto"

    school = School.objects.create(
        name=typed_text.strip(), thana=thana, district_id=thana.district_id,
        verification_status=School.Status.PENDING, source=School.Source.REGISTRATION,
    )
    return school, "created"


# ---- Adding & removing schools (dashboard) ------------------------------- #
def same_name_school(thana, name, *, district_id=None, exclude=None):
    """A live school whose name or an alias is `name` once normalised, else None. Looked for in the
    thana plus its district's schools without an area or, with `thana=None`, in the whole district
    `district_id` (see school_scope). `exclude`: a school to leave out (the one being moved or restored)."""
    qn = normalize_school_name(name)
    other = ~Q(pk=exclude.pk) if exclude else Q()
    school = (_alive_schools().select_related("thana", "district")  # messages show its location
              .filter(school_scope(thana, district_id), other, name_normalized=qn).first())
    if school:
        return school
    alias = (SchoolAlias.objects.select_related("school")
             .filter(school_scope(thana, district_id, prefix="school__"), school__is_deleted=False,
                     alias_normalized=qn))
    if exclude:
        alias = alias.exclude(school=exclude)
    alias = alias.first()
    return alias.school.canonical() if alias else None


def similar_schools(thana, name, limit=8, *, district_id=None):
    """Live schools (looked for as in same_name_school) whose name or an alias is as close to `name`
    as the duplicate review would flag (SCHOOL_DUPLICATE_THRESHOLD), closest first."""
    qn = normalize_school_name(name)
    alias_score = (SchoolAlias.objects.filter(school=OuterRef("pk"))
                   .annotate(s=TrigramSimilarity("alias_normalized", Value(qn))).order_by("-s").values("s")[:1])
    return list(
        _alive_schools().select_related("thana", "district").filter(school_scope(thana, district_id))
        .annotate(score=Greatest(TrigramSimilarity("name_normalized", Value(qn)),
                                 Coalesce(Subquery(alias_score, output_field=FloatField()), Value(0.0))))
        .filter(score__gte=settings.WIKISCHOLAR["SCHOOL_DUPLICATE_THRESHOLD"])
        .order_by("-score", "name")[:limit]
    )


@transaction.atomic
def add_school(*, thana, name, request):
    school = School.objects.create(
        name=name, thana=thana, district_id=thana.district_id, verification_status=School.Status.VERIFIED,
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
    clash = same_name_school(school.thana, school.name, district_id=school.district_id, exclude=school)
    if clash:
        raise ValueError(f"“{clash.name}” is already listed in {clash.location_label}, so this can't be restored.")
    school.restore()
    audit.record("school.restored", request=request, entity=school)


# ---- Duplicate review & merge --------------------------------------------- #
def find_duplicate_pairs(district_id=None, threshold=None, limit=200):
    threshold = threshold or settings.WIKISCHOLAR["SCHOOL_DUPLICATE_THRESHOLD"]
    sql = """
        SELECT a.id, b.id, similarity(a.name_normalized, b.name_normalized) AS sim
        FROM schools a
        JOIN schools b ON a.district_id = b.district_id AND a.id < b.id
             AND (a.thana_id = b.thana_id OR a.thana_id IS NULL OR b.thana_id IS NULL)
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
    schools = School.objects.select_related("thana", "district").in_bulk(ids)
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
    # Same area; or same district when either one's area isn't known yet.
    if keep.district_id != duplicate.district_id or (
            keep.thana_id and duplicate.thana_id and keep.thana_id != duplicate.thana_id):
        raise ValueError("Schools can only be merged within the same thana "
                         "(or the same district, when one of them has no area yet).")
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
    if not keep.thana_id and duplicate.thana_id:  # the duplicate tells us the area
        keep_before = audit.snapshot(keep)
        keep.thana_id = duplicate.thana_id
        keep.save(update_fields=["thana", "updated_at"])
        audit.record("school.area_set", request=request, entity=keep, before=keep_before,
                     after=audit.snapshot(keep), meta={"from_merge_of": duplicate.pk})
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
def set_school_area(school, thana, *, request):
    """Set (or change) a school's thana within its district. Refused when that area, or the
    district's schools without an area, already list the same name (merge them instead)."""
    if thana.district_id != school.district_id:
        raise ValueError("Choose a thana in the school's own district.")
    if school.thana_id == thana.pk:
        return False
    clash = same_name_school(thana, school.name, exclude=school)
    if clash:
        raise ValueError(f"“{clash.name}” is already listed in {clash.location_label}. "
                         "Merge the two schools from Review duplicates instead.")
    before = audit.snapshot(school)
    school.thana = thana
    school.save()
    audit.record("school.area_set", request=request, entity=school, before=before, after=audit.snapshot(school))
    return True


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
