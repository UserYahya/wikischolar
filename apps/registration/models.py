"""
Registration module: students, email verifications, edit history.
students.wikischolar_id is the cross-module identity for all future modules.
"""
import uuid

from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.core.models import SoftDeleteModel

from .choices import CLASS_CHOICES, CLASS_VALUES, FilledBy, Gender, GuardianRelation, HeardFrom

PHONE_REGEX = r"^01[3-9][0-9]{8}$"


class Student(SoftDeleteModel):
    class SchoolResolution(models.TextChoices):
        SELECTED = "selected", "Picked from suggestions"
        EXACT = "exact", "Exact name match"
        ALIAS = "alias", "Matched a known alias"
        AUTO = "auto", "Auto-matched (high similarity)"
        CREATED = "created", "New school added (pending)"
        ADMIN = "admin", "Set by admin"

    wikischolar_id = models.CharField(max_length=20, unique=True, editable=False)

    # Step 1 — who fills in the form, student & guardian
    filled_by = models.CharField(max_length=10, choices=FilledBy.choices, default=FilledBy.STUDENT)
    guardian_declared_at = models.DateTimeField(null=True, blank=True)  # when the guardian ticked the declaration
    student_name = models.CharField(max_length=150)
    gender = models.CharField(max_length=12, choices=Gender.choices)
    guardian_name = models.CharField(max_length=150)
    guardian_relation = models.CharField(max_length=10, choices=GuardianRelation.choices)
    guardian_relation_other = models.CharField(max_length=60, blank=True)  # only when relation is "other"

    # Step 2 — academic (region is derived from district at read time)
    district = models.ForeignKey("reference.District", on_delete=models.PROTECT, related_name="students")
    upazila = models.ForeignKey("reference.Upazila", on_delete=models.PROTECT, related_name="students")
    school = models.ForeignKey("reference.School", on_delete=models.PROTECT, related_name="students")
    school_name_as_entered = models.CharField(max_length=255)
    school_resolution = models.CharField(max_length=10, choices=SchoolResolution.choices)
    current_class = models.CharField(max_length=2, choices=CLASS_CHOICES, db_index=True)
    class_roll = models.CharField(max_length=20, blank=True)  # digits only (checked by the form)
    student_id_sid = models.CharField(max_length=40, blank=True)
    section = models.CharField(max_length=20, blank=True)  # optional: only classes that have sections

    # Step 3 — contact
    phone = models.CharField(max_length=11, db_index=True)
    email = models.EmailField(db_index=True)
    email_verified_at = models.DateTimeField()

    # Step 4 — consent
    policy_consent_at = models.DateTimeField()
    policy_version = models.CharField(max_length=20)
    updates_opt_in = models.BooleanField(default=False)

    # Survey: how the family heard about WikiScholar (blank for students registered before it was asked)
    heard_from = models.CharField(max_length=20, choices=HeardFrom.choices, blank=True)

    source_ip = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        db_table = "students"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["district", "upazila"], name="student_location_idx"),
            models.Index(fields=["school"], name="student_school_idx"),
            models.Index(fields=["gender"], name="student_gender_idx"),
        ]
        constraints = [
            models.CheckConstraint(condition=~Q(class_roll="") | ~Q(student_id_sid=""), name="student_roll_or_sid"),
            models.CheckConstraint(condition=Q(phone__regex=PHONE_REGEX), name="student_phone_bd_format"),
            models.CheckConstraint(condition=Q(current_class__in=CLASS_VALUES), name="student_class_6_to_10"),
            models.CheckConstraint(
                condition=(Q(guardian_relation=GuardianRelation.OTHER) & ~Q(guardian_relation_other=""))
                | (~Q(guardian_relation=GuardianRelation.OTHER) & Q(guardian_relation_other="")),
                name="student_relation_other_text"),
            models.CheckConstraint(
                condition=(Q(filled_by=FilledBy.GUARDIAN) & Q(guardian_declared_at__isnull=False))
                | (Q(filled_by=FilledBy.STUDENT) & Q(guardian_declared_at__isnull=True)),
                name="student_guardian_declaration"),
            models.CheckConstraint(condition=Q(heard_from__in=["", *HeardFrom.values]), name="student_heard_from_valid"),
        ]

    def __str__(self):
        return f"{self.wikischolar_id} {self.student_name}"

    @property
    def guardian_relation_label(self):
        if self.guardian_relation == GuardianRelation.OTHER and self.guardian_relation_other:
            return self.guardian_relation_other
        return self.get_guardian_relation_display()

    @property
    def region(self):
        from apps.reference.services import region_for_district
        return region_for_district(self.district)


class EmailVerification(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        VERIFIED = "verified", "Verified"
        USED = "used", "Used for a registration"
        SUPERSEDED = "superseded", "Replaced by a newer code"
        LOCKED = "locked", "Too many wrong attempts"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(db_index=True)
    code_hash = models.CharField(max_length=64)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    attempts = models.PositiveSmallIntegerField(default=0)
    expires_at = models.DateTimeField()
    verified_at = models.DateTimeField(null=True, blank=True)
    used_at = models.DateTimeField(null=True, blank=True)
    student = models.ForeignKey(Student, null=True, blank=True, on_delete=models.PROTECT,
                                related_name="email_verifications")
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "email_verifications"
        ordering = ["-created_at"]

    @property
    def is_expired(self):
        return timezone.now() >= self.expires_at


class EditHistory(models.Model):
    """One row per changed field. Append-only (enforced by DB trigger)."""
    student = models.ForeignKey(Student, on_delete=models.PROTECT, related_name="edit_history")
    change_set = models.UUIDField(default=uuid.uuid4, db_index=True)
    field_name = models.CharField(max_length=64)
    old_value = models.JSONField(null=True, blank=True, encoder=DjangoJSONEncoder)
    new_value = models.JSONField(null=True, blank=True, encoder=DjangoJSONEncoder)
    reason = models.CharField(max_length=255, blank=True)
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                   related_name="+")
    changed_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        db_table = "edit_history"
        ordering = ["-changed_at", "-id"]
