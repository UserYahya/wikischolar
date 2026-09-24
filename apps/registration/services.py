"""Public interface of the Registration module."""
import hashlib
import hmac
import secrets
import uuid
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.core import audit, ids
from apps.notifications import services as notify
from apps.notifications.models import NotificationLog
from apps.reference import services as reference

from . import emails
from .choices import FilledBy
from .models import EditHistory, EmailVerification, Student

CFG = settings.WIKISCHOLAR


# ---- Email OTP -------------------------------------------------------------- #
def _hash(code, verification_id):
    msg = f"{verification_id}:{code}".encode()
    return hmac.new(settings.SECRET_KEY.encode(), msg, hashlib.sha256).hexdigest()


def start_email_verification(email, *, request):
    from apps.core.utils import client_ip
    EmailVerification.objects.filter(email=email, status=EmailVerification.Status.PENDING).update(
        status=EmailVerification.Status.SUPERSEDED)
    code = f"{secrets.randbelow(1_000_000):06d}"
    ev = EmailVerification(email=email, ip_address=client_ip(request),
                           expires_at=timezone.now() + timedelta(minutes=CFG["OTP_TTL_MINUTES"]))
    ev.id = uuid.uuid4()
    ev.code_hash = _hash(code, ev.id)
    ev.save()
    subject, body = notify.render_system_email(emails.OTP, {"code": code, "minutes": CFG["OTP_TTL_MINUTES"]})
    log = notify.send_transactional_email(NotificationLog.Kind.OTP, email, subject, body)
    return ev, code, log


def check_email_code(verification_id, code):
    """Returns (ok, error_code)."""
    ev = EmailVerification.objects.select_for_update().filter(pk=verification_id).first()
    if ev is None:
        return False, "not_found"
    if ev.status == EmailVerification.Status.VERIFIED:
        return True, ""
    if ev.status != EmailVerification.Status.PENDING:
        return False, ev.status
    if ev.is_expired:
        return False, "expired"
    ev.attempts += 1
    if hmac.compare_digest(ev.code_hash, _hash(code.strip(), ev.id)):
        ev.status, ev.verified_at = EmailVerification.Status.VERIFIED, timezone.now()
        ev.save(update_fields=["status", "verified_at", "attempts"])
        return True, ""
    if ev.attempts >= CFG["OTP_MAX_ATTEMPTS"]:
        ev.status = EmailVerification.Status.LOCKED
    ev.save(update_fields=["status", "attempts"])
    return False, "locked" if ev.status == EmailVerification.Status.LOCKED else "wrong_code"


def usable_verification(verification_id, email):
    window = timezone.now() - timedelta(minutes=CFG["OTP_VERIFIED_WINDOW_MINUTES"])
    return (EmailVerification.objects.select_for_update()
            .filter(pk=verification_id, email=email, status=EmailVerification.Status.VERIFIED,
                    verified_at__gte=window).first())


# ---- Registration ---------------------------------------------------------- #
@transaction.atomic
def register_student(data, *, request):
    """`data` is RegistrationForm.cleaned_data. Raises ValueError('email_not_verified')."""
    from apps.core.utils import client_ip
    ev = usable_verification(data["verification_id"], data["email"])
    if ev is None:
        raise ValueError("email_not_verified")

    school, how = reference.resolve_school(upazila=data["upazila"], typed_text=data["school_name"],
                                           school_id=data.get("school_id"))
    now = timezone.now()
    student = Student.objects.create(
        wikischolar_id=ids.next_wikischolar_id(),
        student_name=data["student_name"], date_of_birth=data["date_of_birth"], gender=data["gender"],
        guardian_name=data["guardian_name"], guardian_relation=data["guardian_relation"],
        guardian_relation_other=data["guardian_relation_other"],
        district=data["district"], upazila=data["upazila"], school=school,
        school_name_as_entered=data["school_name"], school_resolution=how,
        current_class=data["current_class"], class_roll=data["class_roll"], student_id_sid=data["student_id_sid"],
        phone=data["phone"], email=data["email"], email_verified_at=ev.verified_at,
        policy_consent_at=now, policy_version=CFG["POLICY_VERSION"], updates_opt_in=data["updates_opt_in"],
        filled_by=FilledBy.GUARDIAN if data.get("guardian_declaration") else FilledBy.STUDENT,
        guardian_declared_at=now if data.get("guardian_declaration") else None,
        source_ip=client_ip(request),
    )
    ev.status, ev.used_at, ev.student = EmailVerification.Status.USED, now, student
    ev.save(update_fields=["status", "used_at", "student"])
    audit.record("student.registered", request=request, actor_type="public", entity=student,
                 meta={"school_resolution": how, "school_id": school.pk, "filled_by": student.filled_by})
    transaction.on_commit(lambda: send_confirmation(student))
    return student


def summary(student):
    region = student.region
    return {
        "wikischolar_id": student.wikischolar_id,
        "student_name": student.student_name,
        "date_of_birth": student.date_of_birth.isoformat(),
        "gender": student.get_gender_display(),
        "guardian": f"{student.guardian_name} ({student.guardian_relation_label})",
        "district": student.district.name,
        "region": region.name if region else "",
        "upazila": student.upazila.name,
        "school": student.school.name,
        "school_pending": student.school.verification_status == "pending",
        "current_class": student.get_current_class_display(),
        "class_roll": student.class_roll,
        "student_id_sid": student.student_id_sid,
        "phone": student.phone,
        "email": student.email,
        "filled_by": student.get_filled_by_display(),
    }


def send_confirmation(student):
    subject, body = notify.render_system_email(emails.CONFIRMATION, emails.confirmation_values(summary(student)))
    notify.send_transactional_email(NotificationLog.Kind.CONFIRMATION, student.email, subject, body, student=student)


# ---- Admin edits (every change → edit_history + audit_logs) ------------------ #
EDITABLE_FIELDS = ["student_name", "date_of_birth", "gender", "guardian_name", "guardian_relation",
                   "guardian_relation_other", "district", "upazila", "school", "current_class", "class_roll",
                   "student_id_sid", "phone", "email", "updates_opt_in"]


def _value(student, field):
    v = getattr(student, field)
    return v.pk if hasattr(v, "pk") else v


@transaction.atomic
def update_student(student, changes, *, request, reason=""):
    student = Student.objects.select_for_update().get(pk=student.pk)
    change_set, before, after, rows = uuid.uuid4(), {}, {}, []
    for field in EDITABLE_FIELDS:
        if field not in changes:
            continue
        old, new = _value(student, field), changes[field]
        new_cmp = new.pk if hasattr(new, "pk") else new
        if old == new_cmp:
            continue
        before[field], after[field] = old, new_cmp
        rows.append(EditHistory(student=student, change_set=change_set, field_name=field, old_value=old,
                                new_value=new_cmp, reason=reason, changed_by=request.user))
        setattr(student, field, new)
        if field == "school":
            student.school_resolution = Student.SchoolResolution.ADMIN
    if not rows:
        return 0
    student.save()
    EditHistory.objects.bulk_create(rows)
    audit.record("student.updated", request=request, entity=student, before=before, after=after,
                 meta={"change_set": str(change_set), "reason": reason})
    return len(rows)


def reassign_school(*, from_school, to_school, request, reason):
    """Used by the Reference module's merge tool (through this interface only)."""
    moved = []
    change_set = uuid.uuid4()
    rows = []
    for s in Student.all_objects.select_for_update().filter(school=from_school):
        rows.append(EditHistory(student=s, change_set=change_set, field_name="school", old_value=from_school.pk,
                                new_value=to_school.pk, reason=reason, changed_by=request.user))
        moved.append(s.wikischolar_id)
    Student.all_objects.filter(school=from_school).update(school=to_school, updated_at=timezone.now())
    EditHistory.objects.bulk_create(rows)
    return moved


@transaction.atomic
def archive_student(student, *, request, reason=""):
    student.soft_delete(by=request.user)
    audit.record("student.archived", request=request, entity=student, meta={"reason": reason})


@transaction.atomic
def restore_student(student, *, request):
    student.restore()
    audit.record("student.restored", request=request, entity=student)
