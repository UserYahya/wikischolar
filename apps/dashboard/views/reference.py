import csv

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import IntegrityError, OperationalError, transaction
from django.db.models import Count, Q
from django.http import HttpResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.core import audit
from apps.core.permissions import require_perm
from apps.core.utils import english_text
from apps.reference import importer
from apps.reference import services as ref
from apps.reference.models import District, Region, School, Thana

from ..forms import GOVERNMENT_FIELDS, RegionForm, SchoolDetailsForm
from .. import advanced
from . import searches
from ._util import advanced_context, paginate


def _english(request, raw):
    """English-only names (same rule as the public form); None plus an error message otherwise."""
    try:
        return english_text(raw)
    except ValidationError as exc:
        messages.error(request, exc.messages[0])
        return None


def _filtered_schools(request):
    """The Schools list's query (status, district, thana, search box, advanced or saved search), shared
    by the list and its CSV export so both always show the same schools."""
    status = request.GET.get("status", "active")
    qs = (School.all_objects.filter(is_deleted=status == "removed").select_related("district__region", "thana")
          .annotate(n=Count("students", filter=Q(students__is_deleted=False))))
    if status == "active":
        qs = qs.exclude(verification_status="merged")
    elif status and status != "removed":
        qs = qs.filter(verification_status=status)
    district = request.GET.get("district", "")
    if district.isdigit():
        qs = qs.filter(district_id=district)
    thana = request.GET.get("thana") or request.GET.get("upazila", "")  # links from before the rename
    if thana == "none":  # thana not known yet (e.g. imported with the district only)
        qs = qs.filter(thana__isnull=True)
    elif thana.isdigit():
        qs = qs.filter(thana_id=thana)
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(aliases__alias_text__icontains=q) | Q(eiin=q)).distinct()
    saved = searches.for_request(request, "schools")
    adv = advanced.normalize("schools", request.GET.get("adv", "") or (saved.query if saved else ""))
    if adv:
        qs = qs.filter(advanced.parse("schools", adv)[0])
    return qs.order_by("verification_status", "name"), {"status": status, "district": district, "thana": thana,
                                                         "q": q, "adv": adv}


@require_perm("schools.view")
def school_list(request):
    qs, f = _filtered_schools(request)
    try:
        with advanced.time_limit(bool(f["adv"])):
            return _school_list_page(request, qs, f)
    except OperationalError:  # the advanced search hit the time limit
        messages.error(request, "That advanced search took too long. Narrow it down (e.g. pick a district) and try again.")
        return redirect("dashboard:schools")


SCHOOL_EXPORT_COLUMNS = [
    ("school_id", lambda s: s.pk), ("eiin", lambda s: s.eiin), ("name", lambda s: s.name),
    ("status", lambda s: "removed" if s.is_deleted else s.verification_status), ("source", lambda s: s.source),
    ("region", lambda s: s.district.region.name if s.district.region_id else ""),
    ("district", lambda s: s.district.name), ("division", lambda s: s.division),
    ("thana", lambda s: s.thana.name if s.thana_id else ""), ("post_office", lambda s: s.post_office),
    ("institute_type", lambda s: s.get_institute_type_display()),
    ("education_level", lambda s: s.get_education_level_display()),
    ("management", lambda s: s.get_management_display()), ("mpo", lambda s: s.get_mpo_display()),
    ("institute_for", lambda s: s.get_institute_for_display()),
    ("geographical_position", lambda s: s.get_geographical_position_display()),
    ("area_status", lambda s: s.get_area_status_display()), ("email", lambda s: s.email),
    ("students", lambda s: s.n), ("added_on", lambda s: timezone.localdate(s.created_at).isoformat()),
]


@require_perm("schools.view")
def school_export(request):
    """CSV of exactly the schools the list shows (all pages): quick filters, advanced or saved search."""
    qs, f = _filtered_schools(request)
    rows = qs.count()
    audit.record("schools.exported", request=request, entity_type="schools",
                 meta={"filter": {k: v for k, v in f.items() if v}, "rows": rows})
    writer = csv.writer(_Echo())

    def lines():
        yield "\ufeff"  # BOM so Excel reads it as UTF-8
        yield writer.writerow([c for c, _ in SCHOOL_EXPORT_COLUMNS])
        for s in qs.iterator(chunk_size=2000):
            yield writer.writerow([fn(s) for _, fn in SCHOOL_EXPORT_COLUMNS])

    resp = StreamingHttpResponse(lines(), content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="schools-{timezone.localdate():%Y-%m-%d}.csv"'
    return resp


class _Echo:
    def write(self, value):
        return value


def _school_list_page(request, qs, f):
    page, qstring = paginate(request, qs)
    return render(request, "dashboard/schools.html", {
        "page": page, "qstring": qstring, "districts": District.objects.all(),
        "thanas": ref.areas_of(f["district"]) if f["district"] else [],
        "f": f, "can_edit": request.user.has_perm_code("schools.edit"),
        **advanced_context(request, "schools", f["adv"]),
    })


@require_perm("schools.edit")
def school_add(request):
    """Add a verified school. An exact name or alias in the thana is refused; a similar name asks
    for confirmation, so the dashboard doesn't create the duplicates the merge screen cleans up."""
    data = {"district": request.GET.get("district", ""), "thana": request.GET.get("thana", ""), "name": ""}
    errors, same, similar = {}, None, []
    if request.method == "POST":
        data = {k: request.POST.get(k, "").strip() for k in ("district", "thana", "name")}
        th = Thana.objects.filter(pk=data["thana"] if data["thana"].isdigit() else 0,
                                     district_id=data["district"] if data["district"].isdigit() else 0).first()
        if not th:
            errors["thana"] = "Choose the district and thana."
        name = ""
        if not data["name"]:
            errors["name"] = "Enter the school's official name."
        else:
            try:
                name = english_text(data["name"])
            except ValidationError as exc:
                errors["name"] = exc.messages[0]
            if len(name) > 255:
                errors["name"] = "Keep the name under 255 characters."
        if not errors:
            same = ref.same_name_school(th, name)
            if same:
                errors["name"] = "This school is already listed."
            else:
                similar = [] if request.POST.get("confirm") else ref.similar_schools(th, name)
                if not similar:
                    school = ref.add_school(thana=th, name=name, request=request)
                    messages.success(request, f"Added “{school.name}” to {th.name}.")
                    return redirect("dashboard:school", pk=school.pk)
    return render(request, "dashboard/school_add.html", {
        "d": data, "errors": errors, "same": same, "similar": similar, "districts": District.objects.all(),
        "thanas": ref.areas_of(data["district"]) if data["district"].isdigit() else [],
    })


IMPORT_SESSION_KEY = "school_import"


@require_perm("schools.edit")
def school_import(request):
    """Upload a CSV, preview what each row would do, then confirm. The parsed rows wait in the
    session between the two steps and are checked again on confirm."""
    ctx = {"districts": District.objects.all(), "max_rows": importer.MAX_ROWS}
    if request.method == "POST" and request.POST.get("op") == "confirm":
        pending = request.session.pop(IMPORT_SESSION_KEY, None)
        if not pending:
            messages.error(request, "That upload has expired. Please upload the file again.")
            return redirect("dashboard:school_import")
        add = {int(x) for x in request.POST.getlist("add_similar") if x.isdigit()}
        created, planned = importer.apply(pending["rows"], status=pending["status"], add_similar=add, request=request)
        skipped = len(planned) - len(created)
        messages.success(request, f"Imported {len(created)} school{'s' if len(created) != 1 else ''} from "
                         f"{pending['file']}." + (f" {skipped} row{'s were' if skipped != 1 else ' was'} not added "
                                                  f"(already listed, repeated, similar or with errors)." if skipped else ""))
        return redirect("dashboard:schools")
    if request.method == "POST":
        upload = request.FILES.get("file")
        status = request.POST.get("status")
        status = status if status in (School.Status.VERIFIED, School.Status.PENDING) else School.Status.VERIFIED
        if not upload:
            ctx["file_error"] = "Choose a CSV file to upload."
        else:
            try:
                rows = importer.read_rows(upload.read(importer.MAX_BYTES + 1))
            except importer.ImportFileError as exc:
                ctx["file_error"] = str(exc)
            else:
                planned = importer.plan(rows)
                request.session[IMPORT_SESSION_KEY] = {"rows": rows, "status": status, "file": upload.name}
                ctx.update(planned=planned, counts=importer.summary(planned), file_name=upload.name,
                           status_label=School.Status(status).label)
        ctx["status"] = status
    return render(request, "dashboard/school_import.html", ctx)


def _csv_download(body, filename):
    resp = HttpResponse(body, content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp


@require_perm("schools.edit")
def school_import_template(request):
    return _csv_download(importer.template_csv(), "schools-import-template.csv")


@require_perm("schools.edit")
def school_import_locations(request):
    district = District.objects.filter(pk=request.GET.get("district") or 0).first()
    suffix = f"-{district.name.lower().replace(' ', '-')}" if district else ""
    return _csv_download(importer.locations_csv(district), f"districts-and-thanas{suffix}.csv")


@require_perm("schools.view")
def school_detail(request, pk):
    school = get_object_or_404(School.all_objects.select_related("district__region", "thana", "merged_into"), pk=pk)
    details_form = SchoolDetailsForm(instance=school)
    if request.method == "POST":
        if not request.user.has_perm_code("schools.edit"):
            messages.error(request, "You don't have permission to edit schools.")
            return redirect("dashboard:school", pk=pk)
        op = request.POST.get("op")
        if op == "details" and not school.is_deleted:
            before = audit.snapshot(school, fields=GOVERNMENT_FIELDS)
            details_form = SchoolDetailsForm(request.POST, instance=school)
            if details_form.is_valid():
                details_form.save()
                audit.record("school.details_updated", request=request, entity=school, before=before,
                             after=audit.snapshot(school, fields=GOVERNMENT_FIELDS))
                messages.success(request, "Government data saved.")
                return redirect("dashboard:school", pk=pk)
            school.refresh_from_db()
        elif op == "remove":
            try:
                ref.remove_school(school, request=request, reason=request.POST.get("reason", ""))
            except ValueError as exc:
                messages.error(request, str(exc))
                return redirect("dashboard:school", pk=pk)
            messages.success(request, f"Removed “{school.name}”. You can restore it from Schools → Removed.")
            return redirect(f"{reverse('dashboard:schools')}?district={school.district_id}"
                            + (f"&thana={school.thana_id}" if school.thana_id else ""))
        if op == "restore":
            try:
                ref.restore_school(school, request=request)
            except ValueError as exc:
                messages.error(request, str(exc))
            else:
                messages.success(request, "Restored.")
            return redirect("dashboard:school", pk=pk)
        if school.is_deleted:
            messages.error(request, "Restore this school before changing it.")
        elif op == "verify":
            ref.set_school_status(school, School.Status.VERIFIED, request=request)
            messages.success(request, "Marked as verified.")
        elif op == "unverify":
            ref.set_school_status(school, School.Status.PENDING, request=request)
            messages.success(request, "Moved back to pending review.")
        elif op == "set_area":
            th = Thana.objects.filter(pk=request.POST.get("thana") or 0, district_id=school.district_id).first()
            if not th:
                messages.error(request, "Choose a thana.")
            else:
                try:
                    changed = ref.set_school_area(school, th, request=request)
                except ValueError as exc:
                    messages.error(request, str(exc))
                else:
                    if changed:
                        messages.success(request, f"Thana set to {th.name}.")
        elif op == "rename" and request.POST.get("name", "").strip():
            if (name := _english(request, request.POST["name"])) is not None:
                ref.rename_school(school, name, request=request)
                messages.success(request, "Renamed. The previous name was kept as an alias.")
        elif op == "alias" and request.POST.get("alias", "").strip():
            if (alias := _english(request, request.POST["alias"])) is not None:
                ref.add_alias(school, alias, request=request)
                messages.success(request, "Alias added. Matching entries will now resolve to this school.")
        if not details_form.is_bound:  # an invalid details form is shown again with its errors
            return redirect("dashboard:school", pk=pk)
    students = school.students.select_related("district")[:100]
    entered = (school.students.values("school_name_as_entered").annotate(n=Count("id")).order_by("-n")[:20])
    return render(request, "dashboard/school_detail.html", {
        "school": school, "aliases": school.aliases.select_related("created_by"),
        "students": students, "student_count": school.students.count(), "entered": entered,
        "merged_from": school.merged_from.all(), "can_edit": request.user.has_perm_code("schools.edit"),
        "removal_blocker": "" if school.is_deleted else ref.removal_blocker(school),
        "details_form": details_form, "edit_details": details_form.is_bound,
        "areas": ref.areas_of(school.district_id),
    })


@require_perm("schools.merge")
def duplicates(request):
    district = request.GET.get("district") or None
    try:
        threshold = float(request.GET.get("threshold") or 0) or None
    except ValueError:
        threshold = None
    pairs = ref.find_duplicate_pairs(district_id=district, threshold=threshold)
    counts = dict(School.objects.filter(pk__in={s.pk for a, b, _ in pairs for s in (a, b)})
                  .annotate(n=Count("students", filter=Q(students__is_deleted=False))).values_list("pk", "n"))
    return render(request, "dashboard/duplicates.html", {
        "pairs": [(a, b, sim, counts.get(a.pk, 0), counts.get(b.pk, 0)) for a, b, sim in pairs],
        "districts": District.objects.all(), "district": district or "", "threshold": threshold or "",
    })


@require_POST
@require_perm("schools.merge")
def merge(request):
    keep = get_object_or_404(School, pk=request.POST.get("keep"))
    dup = get_object_or_404(School, pk=request.POST.get("duplicate"))
    try:
        moved = ref.merge_schools(keep=keep, duplicate=dup, request=request)
    except ValueError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, f"Merged “{dup.name}” into “{keep.name}”. {moved} student(s) re-linked.")
    return redirect(request.POST.get("next") or "dashboard:duplicates")


@require_perm("reference.view")
def locations(request):
    can_edit = request.user.has_perm_code("reference.edit")
    region_form = RegionForm(request.POST if request.POST.get("op") == "add_region" else None)
    if request.method == "POST":
        if not can_edit:
            messages.error(request, "You don't have permission to change reference data.")
            return redirect("dashboard:locations")
        op = request.POST.get("op")
        if op == "add_region" and region_form.is_valid():
            region = region_form.save()
            audit.record("reference.region_created", request=request, entity=region, after=audit.snapshot(region))
            messages.success(request, f"Region “{region.name}” added.")
            return redirect("dashboard:locations")
        if op == "rename_region":
            region = get_object_or_404(Region, pk=request.POST.get("region"))
            before = audit.snapshot(region)
            name = _english(request, request.POST.get("name", ""))
            if name is None:
                return redirect("dashboard:locations")
            region.name = name or region.name
            region.name_bn = request.POST.get("name_bn", region.name_bn).strip()
            region.save()
            audit.record("reference.region_updated", request=request, entity=region, before=before,
                         after=audit.snapshot(region))
            messages.success(request, "Region updated.")
            return redirect("dashboard:locations")
        if op == "archive_region":
            region = get_object_or_404(Region, pk=request.POST.get("region"))
            if region.districts.exists():
                messages.error(request, "Move this region's districts to another region first.")
            else:
                region.soft_delete(by=request.user)
                audit.record("reference.region_archived", request=request, entity=region)
                messages.success(request, f"Region “{region.name}” archived.")
            return redirect("dashboard:locations")
        if op == "assign":
            regions = {str(r.pk): r for r in Region.objects.all()}
            changed = 0
            with transaction.atomic():
                for d in District.objects.select_related("region"):
                    key = f"region_{d.pk}"
                    if key in request.POST:
                        changed += ref.assign_district_region(d, regions.get(request.POST[key]), request=request)
            messages.success(request, f"{changed} district assignment(s) updated." if changed else "No changes.")
            return redirect("dashboard:locations")
    regions = Region.objects.annotate(n=Count("districts", distinct=True),
                                      s=Count("districts__students", distinct=True,
                                      filter=Q(districts__students__is_deleted=False)))
    districts = (District.objects.select_related("region")
                 .annotate(th=Count("thanas", distinct=True),
                           s=Count("students", distinct=True, filter=Q(students__is_deleted=False)))
                 .order_by("region__sort_order", "name"))
    return render(request, "dashboard/locations.html", {
        "regions": regions, "districts": districts, "region_form": region_form, "can_edit": can_edit,
        "unassigned": [d for d in districts if not d.region_id],
    })


@require_perm("reference.view")
def district_detail(request, pk):
    district = get_object_or_404(District.objects.select_related("region"), pk=pk)
    if request.method == "POST":
        if not request.user.has_perm_code("reference.edit"):
            messages.error(request, "You don't have permission to change reference data.")
            return redirect("dashboard:district", pk=pk)
        op = request.POST.get("op")
        try:
            with transaction.atomic():
                name = _english(request, request.POST.get("name", ""))
                if name is None:
                    return redirect("dashboard:district", pk=pk)
                if op == "add_thana" and name:
                    # Optional group: one already used anywhere (Cantonment, Other, or a custom one)
                    groups = dict(_area_groups())
                    group = request.POST.get("group", "")
                    group = group if group in groups else ""
                    u = Thana.objects.create(district=district, name=name, group=group, group_bn=groups.get(group, ""),
                                               name_bn=request.POST.get("name_bn", "").strip())
                    audit.record("reference.thana_created", request=request, entity=u, after=audit.snapshot(u))
                    messages.success(request, f"Thana “{u.name}” added.")
                elif op == "rename_thana":
                    u = get_object_or_404(Thana, pk=request.POST.get("thana"), district=district)
                    before = audit.snapshot(u)
                    u.name = name or u.name
                    u.name_bn = request.POST.get("name_bn", u.name_bn).strip()
                    u.save()
                    audit.record("reference.thana_updated", request=request, entity=u, before=before,
                                 after=audit.snapshot(u))
                    messages.success(request, "Thana updated.")
        except IntegrityError:
            messages.error(request, "A thana with this name already exists in this district.")
        return redirect("dashboard:district", pk=pk)
    thanas = district.thanas.annotate(s=Count("students", distinct=True, filter=Q(students__is_deleted=False)),
                                         sc=Count("schools", distinct=True, filter=~Q(schools__verification_status="merged")))
    return render(request, "dashboard/district_detail.html", {
        "district": district, "thanas": ref.sort_areas(thanas), "other_groups": _area_groups(),
        "can_edit": request.user.has_perm_code("reference.edit")})


def _area_groups():
    """[(group, group_bn), ...] of the thana groups in use (Cantonment, Other, any custom one)."""
    rows = Thana.objects.exclude(group="").values_list("group", "group_bn").distinct().order_by("group")
    return list(dict(rows).items())
