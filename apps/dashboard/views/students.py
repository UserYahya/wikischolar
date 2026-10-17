import csv

from django.contrib import messages
from django.db import OperationalError
from django.http import StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.core import audit
from apps.core.models import AuditLog
from apps.core.permissions import require_perm
from apps.notifications import services as notify
from apps.reference import services as ref
from apps.reference.models import District, Region, School, Thana
from apps.registration import services
from apps.registration.choices import CLASS_CHOICES, FilledBy, Gender
from apps.registration.models import Student

from .. import advanced, filters
from ..forms import StudentEditForm
from ._util import advanced_context, paginate


def _filter_context(p):
    ctx = {"regions": Region.objects.prefetch_related("districts"),
           "unassigned_districts": District.objects.filter(region__isnull=True),
           "classes": CLASS_CHOICES, "genders": Gender.choices, "p": p, "sorts": filters.SORTS,
           "msg_batches": notify.recent_batches(), "msg_batch_modes": filters.MSG_BATCH_MODES,
           "filled_by_choices": FilledBy.choices, "area_kinds": filters.AREA_KINDS}
    if len(p["district"]) == 1:
        ctx["thanas"] = ref.areas_of(p["district"][0])
    if p["thana"]:  # the area's schools plus the district's schools without an area
        ctx["schools"] = School.objects.filter(ref.school_scope(Thana.objects.filter(pk=p["thana"]).first()),
                                               merged_into__isnull=True) if str(p["thana"]).isdigit() else []
    return ctx


@require_perm("students.view")
def student_list(request):
    p = filters.params_from(request.GET)
    try:
        with advanced.time_limit(bool(p["adv"])):
            return _student_list(request, p)
    except OperationalError:  # the advanced search hit the time limit
        messages.error(request, "That advanced search took too long. Narrow it down (e.g. pick a district) and try again.")
        return redirect("dashboard:students")


def _student_list(request, p):
    qs = filters.apply(p)
    page, qstring = paginate(request, qs)
    ctx = _filter_context(p)
    ctx.update({"page": page, "qstring": qstring, "count": page.paginator.count,
                "active_filters": filters.active_count(p),
                "can_message": request.user.has_perm_code("messages.send"),
                "can_export": request.user.has_perm_code("students.export")})
    ctx.update(advanced_context(request, "students", p["adv"]))
    if p["batch_size"]:
        total = filters.apply({**p, "batch": ""}).count() if p["batch"] else page.paginator.count
        params = request.GET.copy()
        params.pop("page", None)
        params["sort"] = p["sort"]
        rows = filters.batches(p, total)
        for b in rows:
            params["batch"] = b["number"]
            b["qstring"] = params.urlencode()
        params.pop("batch", None)
        ctx.update({"batches": rows, "batch_total": total, "all_qstring": params.urlencode()})
    return render(request, "dashboard/students.html", ctx)


class _Echo:
    def write(self, value):
        return value


EXPORT_COLUMNS = [
    ("wikischolar_id", lambda s: s.wikischolar_id), ("student_name", lambda s: s.student_name),
    ("gender", lambda s: s.gender),
    ("guardian_name", lambda s: s.guardian_name), ("guardian_relation", lambda s: s.guardian_relation),
    ("guardian_relation_other", lambda s: s.guardian_relation_other),
    ("filled_by", lambda s: s.filled_by),
    ("guardian_declared_at", lambda s: s.guardian_declared_at.isoformat() if s.guardian_declared_at else ""),
    ("region", lambda s: s.district.region.name if s.district.region_id else ""),
    ("district", lambda s: s.district.name), ("thana", lambda s: s.thana.name),
    ("area_group", lambda s: s.thana.group),
    ("school_id", lambda s: s.school_id), ("school", lambda s: s.school.name), ("school_eiin", lambda s: s.school.eiin),
    ("school_management", lambda s: s.school.get_management_display()),
    ("school_education_level", lambda s: s.school.get_education_level_display()),
    ("school_mpo", lambda s: s.school.get_mpo_display()),
    ("school_institute_for", lambda s: s.school.get_institute_for_display()),
    ("school_area_status", lambda s: s.school.get_area_status_display()),
    ("school_name_as_entered", lambda s: s.school_name_as_entered), ("current_class", lambda s: s.current_class),
    ("class_roll", lambda s: s.class_roll), ("student_id_sid", lambda s: s.student_id_sid),
    ("section", lambda s: s.section),
    ("phone", lambda s: s.phone), ("email", lambda s: s.email), ("updates_opt_in", lambda s: s.updates_opt_in),
    ("photo_consent", lambda s: s.photo_consent),
    ("photo_consent_at", lambda s: s.photo_consent_at.isoformat() if s.photo_consent_at else ""),
    ("heard_from", lambda s: s.heard_from),
    ("registered_at", lambda s: s.created_at.isoformat()),
]


@require_perm("students.export")
def student_export(request):
    p = filters.params_from(request.GET)
    qs = filters.apply(p)
    audit.record("students.exported", request=request, entity_type="students",
                 meta={"filter": filters.snapshot(p), "rows": qs.count()})
    writer = csv.writer(_Echo())

    def rows():
        yield "\ufeff"  # BOM so Excel reads Bangla correctly
        yield writer.writerow([c for c, _ in EXPORT_COLUMNS])
        for s in qs.iterator(chunk_size=1000):
            yield writer.writerow([fn(s) for _, fn in EXPORT_COLUMNS])

    resp = StreamingHttpResponse(rows(), content_type="text/csv; charset=utf-8")
    name = f"wikischolar-students-batch-{p['batch']}.csv" if p["batch"] else "wikischolar-students.csv"
    resp["Content-Disposition"] = f'attachment; filename="{name}"'
    return resp


@require_perm("students.view")
def student_detail(request, wsid):
    student = get_object_or_404(Student.all_objects.select_related("district__region", "thana", "school"),
                                wikischolar_id=wsid)
    audit.record("student.viewed", request=request, entity=student)
    history = student.edit_history.select_related("changed_by")[:200]
    return render(request, "dashboard/student_detail.html", {
        "s": student, "history": history,
        "notifications": student.notifications.select_related("email_batch", "sms_batch")[:100],
        "audit": AuditLog.objects.filter(entity_type="students", entity_id=wsid).select_related("actor")[:50],
        "verification": student.email_verifications.first(),
        "can_edit": request.user.has_perm_code("students.edit"),
        "can_delete": request.user.has_perm_code("students.delete"),
    })


@require_perm("students.edit")
def student_edit(request, wsid):
    student = get_object_or_404(Student, wikischolar_id=wsid)
    initial = {f: getattr(student, f) for f in services.EDITABLE_FIELDS}
    form = StudentEditForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        changed = services.update_student(student, {f: d[f] for f in services.EDITABLE_FIELDS if f in d},
                                          request=request, reason=d.get("reason", ""))
        messages.success(request, f"Saved {changed} change(s)." if changed else "Nothing changed.")
        return redirect("dashboard:student", wsid=wsid)
    district_id = form.data.get("district") if form.is_bound else student.district_id
    thana_id = form.data.get("thana") if form.is_bound else student.thana_id
    return render(request, "dashboard/student_edit.html", {
        "s": student, "form": form,
        "districts": District.objects.all(),
        "thanas": ref.areas_of(district_id),
        "schools": _school_choices(thana_id, student.school),
    })


def _school_choices(thana_id, current):
    """The editor's school list: schools of the selected thana and the district's schools
    without an area, plus the student's current school when it is elsewhere (so saving other changes
    never switches the school)."""
    thana = Thana.objects.filter(pk=thana_id or 0).first()
    schools = list(School.objects.filter(ref.school_scope(thana), merged_into__isnull=True)
                   .select_related("thana")) if thana else []
    if current and all(s.pk != current.pk for s in schools):
        schools.insert(0, current)
    return schools


@require_POST
@require_perm("students.delete")
def student_archive(request, wsid):
    student = get_object_or_404(Student, wikischolar_id=wsid)
    services.archive_student(student, request=request, reason=request.POST.get("reason", ""))
    messages.success(request, f"{wsid} moved to archived records. It can be restored at any time.")
    return redirect("dashboard:students")


@require_POST
@require_perm("students.delete")
def student_restore(request, wsid):
    student = get_object_or_404(Student.all_objects.archived(), wikischolar_id=wsid)
    services.restore_student(student, request=request)
    messages.success(request, f"{wsid} restored.")
    return redirect("dashboard:student", wsid=wsid)


@require_perm("students.delete")
def archived(request):
    qs = Student.all_objects.archived().select_related("district", "school", "deleted_by").order_by("-deleted_at")
    page, qstring = paginate(request, qs)
    return render(request, "dashboard/archived.html", {"page": page, "qstring": qstring})
