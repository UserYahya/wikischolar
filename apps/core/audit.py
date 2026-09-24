"""Public interface for writing audit entries. Used by every module."""
from django.forms.models import model_to_dict

from .models import AuditLog
from .utils import client_ip


def snapshot(instance, fields=None, exclude=("password",)):
    """Serializable dict of a model instance for before/after values."""
    if instance is None:
        return None
    data = model_to_dict(instance, fields=fields, exclude=exclude)
    return {k: (str(v) if hasattr(v, "pk") else v) for k, v in data.items()}


def record(action, *, request=None, actor=None, entity=None, entity_type="", entity_id="",
           before=None, after=None, meta=None, actor_type=None):
    if actor is None and request is not None and getattr(request, "user", None) and request.user.is_authenticated:
        actor = request.user
    if entity is not None:
        entity_type = entity_type or entity._meta.db_table
        entity_id = entity_id or str(getattr(entity, "wikischolar_id", None) or entity.pk)
    if actor_type is None:
        actor_type = AuditLog.ActorType.ADMIN if actor else AuditLog.ActorType.PUBLIC
    return AuditLog.objects.create(
        actor=actor,
        actor_type=actor_type,
        actor_label=(actor.email if actor else actor_type),
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id),
        before=before,
        after=after,
        meta=meta or {},
        ip_address=client_ip(request) if request else None,
        user_agent=(request.META.get("HTTP_USER_AGENT", "")[:300] if request else ""),
    )
