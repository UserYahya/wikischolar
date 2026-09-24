"""
Core/Shared module: admins, soft-delete base, audit log, ID sequences.
Every feature module depends on these; core depends on no feature module.
"""
from django.conf import settings
from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from django.utils import timezone


# --------------------------------------------------------------------------- #
# Soft delete: nothing is ever removed from the database.
# --------------------------------------------------------------------------- #
class SoftDeleteQuerySet(models.QuerySet):
    def delete(self):
        raise PermissionError("Hard delete is disabled. Use .soft_delete(by=admin).")

    def soft_delete(self, by=None):
        return self.update(is_deleted=True, deleted_at=timezone.now(), deleted_by=by)

    def alive(self):
        return self.filter(is_deleted=False)

    def archived(self):
        return self.filter(is_deleted=True)


class AliveManager(models.Manager.from_queryset(SoftDeleteQuerySet)):
    """Default manager: hides soft-deleted rows."""

    def get_queryset(self):
        return super().get_queryset().filter(is_deleted=False)


class AllRowsManager(models.Manager.from_queryset(SoftDeleteQuerySet)):
    """Includes archived rows (for the archive view and restores)."""


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(default=timezone.now, db_index=True, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class SoftDeleteModel(TimeStampedModel):
    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.PROTECT, related_name="+",
    )

    objects = AliveManager()
    all_objects = AllRowsManager()

    class Meta:
        abstract = True

    def delete(self, *args, **kwargs):
        raise PermissionError("Hard delete is disabled. Use .soft_delete(by=admin).")

    def soft_delete(self, by=None):
        self.is_deleted, self.deleted_at, self.deleted_by = True, timezone.now(), by
        self.save(update_fields=["is_deleted", "deleted_at", "deleted_by", "updated_at"])

    def restore(self):
        self.is_deleted, self.deleted_at, self.deleted_by = False, None, None
        self.save(update_fields=["is_deleted", "deleted_at", "deleted_by", "updated_at"])


# --------------------------------------------------------------------------- #
# Admins (separate table from students)
# --------------------------------------------------------------------------- #
class Role(models.TextChoices):
    SUPER_ADMIN = "super_admin", "Super Admin"
    ADMIN = "admin", "Admin"
    VIEWER = "viewer", "Read-only Viewer"


class AdminManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, email, password=None, **extra):
        if not email:
            raise ValueError("Email is required")
        user = self.model(email=self.normalize_email(email).lower(), **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra):
        extra.setdefault("role", Role.SUPER_ADMIN)
        return self.create_user(email, password, **extra)


class Admin(AbstractBaseUser):
    email = models.EmailField(unique=True)
    full_name = models.CharField(max_length=150)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.VIEWER)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)
    # Soft delete columns (admins are deactivated, never removed)
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="+")

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS = ["full_name"]
    objects = AdminManager()

    class Meta:
        db_table = "admins"
        ordering = ["full_name"]

    def __str__(self):
        return f"{self.full_name} <{self.email}>"

    def has_perm_code(self, code):
        from .permissions import role_has
        return self.is_active and not self.is_deleted and role_has(self.role, code)


# --------------------------------------------------------------------------- #
# Audit log (append-only; UPDATE/DELETE blocked by DB trigger)
# --------------------------------------------------------------------------- #
class AuditLog(models.Model):
    class ActorType(models.TextChoices):
        ADMIN = "admin", "Admin"
        PUBLIC = "public", "Public (registrant)"
        SYSTEM = "system", "System"

    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                              on_delete=models.PROTECT, related_name="audit_logs")
    actor_type = models.CharField(max_length=10, choices=ActorType.choices)
    actor_label = models.CharField(max_length=254, blank=True)
    action = models.CharField(max_length=64, db_index=True)
    entity_type = models.CharField(max_length=64, blank=True)
    entity_id = models.CharField(max_length=64, blank=True)
    before = models.JSONField(null=True, blank=True, encoder=DjangoJSONEncoder)
    after = models.JSONField(null=True, blank=True, encoder=DjangoJSONEncoder)
    meta = models.JSONField(default=dict, blank=True, encoder=DjangoJSONEncoder)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        db_table = "audit_logs"
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["entity_type", "entity_id"], name="audit_entity_idx")]

    def __str__(self):
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.actor_label} {self.action}"


# --------------------------------------------------------------------------- #
# Human-readable ID sequences (WS-2026-000001, EB-2026-0001, ...)
# --------------------------------------------------------------------------- #
class IdSequence(models.Model):
    scope = models.CharField(max_length=32)
    year = models.PositiveIntegerField()
    last_value = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "id_sequences"
        constraints = [models.UniqueConstraint(fields=["scope", "year"], name="id_seq_scope_year_uniq")]
