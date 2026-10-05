"""
Public interface of the Notification module.

Email and SMS use separate, swappable providers. A failure in one channel (or
one message) is recorded on that log row and never raised to the caller, so
an SMS outage cannot break email delivery or registration.
"""
import hmac
import re
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.module_loading import import_string

from apps.core import audit, ids

from . import html_email
from .models import Channel, EmailBatch, EmailSettings, EmailTemplate, NotificationLog, SmsBatch, SmsSettings

_providers = {}


def provider_for(channel):
    if channel == Channel.SMS:
        cfg = SmsSettings.active()  # credentials saved on the dashboard win over env
        if cfg:
            return cfg.provider_instance()
    key = "EMAIL_PROVIDER" if channel == Channel.EMAIL else "SMS_PROVIDER"
    path = settings.NOTIFICATIONS[key]
    if path not in _providers:
        _providers[path] = import_string(path)()
    return _providers[path]


def render(template, student):
    """Fill {name} and {wikischolar_id}. Plain replacement, so any other braces in the text
    (e.g. "{" in a link or a typo like "{nam}") are sent as typed instead of raising an error."""
    if student is None:
        return template
    return template.replace("{name}", student.student_name).replace("{wikischolar_id}", student.wikischolar_id)


def _deliver(log, body, subject="", html=None):
    """Email always goes out as text + branded HTML: `html` if given, else the provider builds it from the text."""
    provider = provider_for(log.channel)
    extra = {"html": html} if html else {}
    result = provider.send(log.destination, body, subject=subject, **extra)
    log.attempts += 1
    log.provider = provider.name
    log.provider_message_id = result.provider_message_id
    log.status = NotificationLog.Status.SENT if result.ok else NotificationLog.Status.FAILED
    log.error = result.error
    log.sent_at = timezone.now() if result.ok else None
    log.status_updated_at = timezone.now()
    log.save()
    return log


# ---- Editable system emails -------------------------------------------------- #
@dataclass(frozen=True)
class SystemEmail:
    """A system email whose wording a Super Admin can change on Dashboard -> System emails.
    Registered by the module that sends it (e.g. registration: OTP, confirmation)."""
    key: str
    label: str
    description: str
    subject: str                      # default subject
    body: str                         # default body
    placeholders: dict                # {"code": "what it is", ...}; used as {code} in the text
    required: tuple = ()              # placeholders the text must contain
    sample: dict = field(default_factory=dict)  # example values for the preview and test email
    # values -> {placeholder: HTML} for placeholders shown richly in the HTML email (a code box, a table…)
    html_values: Optional[Callable[[dict], dict]] = None


_SYSTEM_EMAILS = {}
_PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")


def register_system_email(email):
    _SYSTEM_EMAILS[email.key] = email


def system_emails():
    return list(_SYSTEM_EMAILS.values())


def get_system_email(key):
    return _SYSTEM_EMAILS[key]


def fill(text, values):
    """Replace {placeholder}s by plain replacement; anything else in braces is left as typed."""
    for name, value in values.items():
        text = text.replace("{" + name + "}", str(value))
    return text


def template_problems(email, subject, body):
    """Why this wording can't be saved (unknown or missing placeholders), or []."""
    problems = []
    used = set(_PLACEHOLDER.findall(f"{subject}\n{body}"))
    unknown = sorted(used - set(email.placeholders))
    if unknown:
        problems.append("Unknown placeholder" + ("s " if len(unknown) > 1 else " ")
                        + ", ".join("{" + u + "}" for u in unknown)
                        + ". Available: " + ", ".join("{" + p + "}" for p in email.placeholders) + ".")
    for name in email.required:
        if name not in used:
            problems.append(f"The email must contain {{{name}}}: {email.placeholders[name]}.")
    return problems


def system_email_text(key):
    """(subject, body, customised row or None): the saved wording, or the module's default."""
    email = get_system_email(key)
    row = EmailTemplate.objects.filter(key=key).select_related("updated_by").first()
    if row and row.is_customized:
        return row.subject, row.body, row
    return email.subject, email.body, row


def render_system_email(key, values):
    subject, body, _ = system_email_text(key)
    return " ".join(fill(subject, values).split()), fill(body, values)


def render_system_email_html(key, values, base_url=None):
    """The HTML part of a system email: the saved wording in the WikiScholar layout."""
    email = get_system_email(key)
    subject, body, _ = system_email_text(key)
    text, fragments = html_email.fill_html(body, values, email.html_values(values) if email.html_values else None)
    return html_email.render_html(text, subject=" ".join(fill(subject, values).split()), fragments=fragments,
                                  base_url=base_url)


@transaction.atomic
def save_system_email(key, subject, body, *, request):
    get_system_email(key)  # KeyError for unknown keys
    before_subject, before_body, row = system_email_text(key)
    row = row or EmailTemplate(key=key)
    row.subject, row.body, row.is_customized = subject, body, True
    row.updated_by, row.updated_at = request.user, timezone.now()
    row.save()
    audit.record("settings.system_email_updated", request=request, entity=row,
                 before={"subject": before_subject, "body": before_body}, after={"subject": subject, "body": body})
    return row


@transaction.atomic
def reset_system_email(key, *, request):
    email = get_system_email(key)
    before_subject, before_body, row = system_email_text(key)
    if row is None or not row.is_customized:
        return False
    row.subject, row.body, row.is_customized = email.subject, email.body, False
    row.updated_by, row.updated_at = request.user, timezone.now()
    row.save()
    audit.record("settings.system_email_reset", request=request, entity=row,
                 before={"subject": before_subject, "body": before_body}, after={"default": True})
    return True


def send_system_email_test(key, to, *, request):
    """Send the saved wording, filled with sample values, through the active email settings."""
    email = get_system_email(key)
    subject, body = render_system_email(key, email.sample)
    result = provider_for(Channel.EMAIL).send(to, body, subject=f"[TEST] {subject}",
                                              html=render_system_email_html(key, email.sample))
    audit.record("settings.system_email_tested", request=request, entity_type="email_templates", entity_id=key,
                 meta={"to": to, "ok": result.ok, "error": result.error})
    return result


# ---- Transactional ---------------------------------------------------------- #
def send_transactional_email(kind, to, subject, body, student=None, html=None):
    log = NotificationLog.objects.create(
        channel=Channel.EMAIL, kind=kind, destination=to, student=student,
        wikischolar_id=student.wikischolar_id if student else "")
    return _deliver(log, body, subject, html=html)


def send_system_email(key, kind, to, values, student=None):
    """Send a registered system email (text + HTML) to one address."""
    subject, body = render_system_email(key, values)
    return send_transactional_email(kind, to, subject, body, student=student,
                                    html=render_system_email_html(key, values))


def email_delivery():
    """How email currently leaves the system: {"delivers": bool, "via": str}.
    Console / in-memory backends only print or keep messages; nothing reaches an inbox."""
    cfg = EmailSettings.active()
    if cfg:
        return {"delivers": cfg.provider != EmailSettings.Provider.CONSOLE, "via": cfg.get_provider_display()}
    backend = settings.EMAIL_BACKEND.rsplit(".", 2)[-2]  # e.g. "console", "smtp", "locmem"
    return {"delivers": backend not in ("console", "locmem", "dummy", "filebased"),
            "via": f"server default ({backend} backend)"}


def sms_delivery():
    """{"delivers": bool, "via": str} for SMS, like email_delivery()."""
    cfg = SmsSettings.active()
    if cfg:
        return {"delivers": cfg.provider != SmsSettings.Provider.CONSOLE, "via": cfg.get_provider_display()}
    path = settings.NOTIFICATIONS["SMS_PROVIDER"]
    return {"delivers": not path.endswith("ConsoleSmsProvider"), "via": f"server default ({path.rsplit('.', 1)[-1]})"}


def send_test_sms(sms_settings, phone):
    """Send through the given (possibly not yet active) SMS settings."""
    return sms_settings.provider_instance().send(
        phone, "WikiScholar test SMS: if you can read this, SMS sending is configured correctly.")


def send_test_email(email_settings, to):
    """Send through the given (possibly not yet active) settings, bypassing the active config."""
    from django.core.mail import EmailMultiAlternatives

    from .providers.base import SendResult
    from .providers.email import reply_to_address
    reply_to = reply_to_address(email_settings)
    body = ("This is a test message from the WikiScholar dashboard.\n\n"
            "If you can read this, outgoing email is configured correctly.\n"
            f"Replies to this email go to: {reply_to or email_settings.from_email}")
    msg = EmailMultiAlternatives(subject="WikiScholar test email", body=body, from_email=email_settings.from_header,
                                 to=[to], connection=email_settings.connection(),
                                 reply_to=[reply_to] if reply_to else None)
    msg.attach_alternative(html_email.render_html(body, subject="WikiScholar test email"), "text/html")
    try:
        msg.send(fail_silently=False)
    except Exception as exc:
        return SendResult(ok=False, error=str(exc)[:500])
    return SendResult(ok=True)


# ---- Bulk batches ---------------------------------------------------------- #
@transaction.atomic
def create_batch(*, channel, students, body, subject="", name="", filter_snapshot=None, opted_in_only=False,
                 request):
    """Create the batch and one queued log per recipient. Nothing is sent yet (see dispatch_batch)."""
    common = {"name": name, "body": body, "filter_snapshot": filter_snapshot or {}, "opted_in_only": opted_in_only,
              "created_by": request.user}
    if channel == Channel.EMAIL:
        batch = EmailBatch.objects.create(batch_code=ids.next_code("email_batch", "EB", width=4), subject=subject,
                                          **common)
    else:
        batch = SmsBatch.objects.create(batch_code=ids.next_code("sms_batch", "SB", width=4), **common)
    fk = "email_batch" if channel == Channel.EMAIL else "sms_batch"
    rows = [NotificationLog(channel=channel, kind=NotificationLog.Kind.BULK, student_id=pk, wikischolar_id=wsid,
                            destination=email if channel == Channel.EMAIL else phone, **{fk: batch})
            for pk, wsid, email, phone in students.order_by().values_list("pk", "wikischolar_id", "email", "phone")]
    NotificationLog.objects.bulk_create(rows, batch_size=1000)
    batch.recipient_count = len(rows)
    batch.save(update_fields=["recipient_count"])
    audit.record("messages.batch_created", request=request, entity=batch,
                 meta={"channel": channel, "name": name, "recipients": len(rows), "filter": filter_snapshot or {}})
    return batch


def dispatch_batch(batch, only_logs=None, time_limit=None):
    """Send the batch's queued messages and return how many are still queued afterwards.

    * Each message is claimed with SELECT ... FOR UPDATE SKIP LOCKED, so the web request, the
      "Send remaining" button and the send_queued cron job can run at the same time without
      sending anything twice. Safe to re-run: only queued rows are sent.
    * With time_limit (seconds) it stops early and leaves the rest queued, so a web request
      finishes before the host's timeout.
    * No server-side cursor stays open across messages (pooled connections such as Neon's
      "-pooler" host don't support that).
    """
    Status = NotificationLog.Status
    if batch.status != batch.Status.SENDING:
        batch.status = batch.Status.SENDING
        batch.save(update_fields=["status"])
    logs = only_logs if only_logs is not None else batch.logs.all()
    pending = list(logs.filter(status=Status.QUEUED).order_by("pk").values_list("pk", flat=True))
    subject = getattr(batch, "subject", "")
    started, tried = time.monotonic(), 0
    for pk in pending:
        # always make progress (at least one message per call), then respect the time limit
        if time_limit is not None and tried and time.monotonic() - started >= time_limit:
            break
        tried += 1
        with transaction.atomic():
            log = (NotificationLog.objects.select_for_update(skip_locked=True, of=("self",))
                   .select_related("student").filter(pk=pk, status=Status.QUEUED).first())
            if log is None:  # another worker has it, or it was already sent
                continue
            _deliver(log, render(batch.body, log.student), render(subject, log.student))
    remaining = batch.logs.filter(status=Status.QUEUED).count()
    if remaining == 0:
        batch.status, batch.completed_at = batch.Status.COMPLETED, timezone.now()
        batch.save(update_fields=["status", "completed_at"])
    return remaining


@transaction.atomic
def queue_resend_failed(batch, *, request):
    """Create fresh queued rows for failed/bounced recipients, linked to the original attempt."""
    fk = "email_batch" if batch.channel == Channel.EMAIL else "sms_batch"
    failed = batch.logs.filter(status__in=[NotificationLog.Status.FAILED, NotificationLog.Status.BOUNCED],
                               resends__isnull=True).select_related("student")
    new = []
    for log in failed:
        dest = log.student.email if batch.channel == Channel.EMAIL else log.student.phone
        new.append(NotificationLog.objects.create(
            channel=batch.channel, kind=log.kind, student=log.student, wikischolar_id=log.wikischolar_id,
            destination=dest, resend_of=log, **{fk: batch}))
    audit.record("messages.resend_failed", request=request, entity=batch, meta={"count": len(new)})
    return NotificationLog.objects.filter(pk__in=[n.pk for n in new])


def batch_stats(batch):
    from django.db.models import Count
    counts = {s: 0 for s in NotificationLog.Status.values}
    counts.update(dict(batch.logs.order_by().values_list("status").annotate(n=Count("id"))))
    counts["not_delivered"] = sum(counts[s] for s in NotificationLog.NOT_DELIVERED)
    return counts


def get_batch(code):
    """EB-… is an email batch, SB-… an SMS batch; None if unknown."""
    model = EmailBatch if str(code).startswith("EB-") else SmsBatch
    return model.objects.select_related("created_by").filter(batch_code=code).first()


def find_batches(*, q="", channel="", problems=False, limit=200):
    """Batches for the Messages list, newest first, with per-status counts.
    q matches the batch name, code or subject; problems=True keeps batches with undelivered messages."""
    from itertools import chain

    from django.db.models import Count, Q
    counts = {
        "n_delivered": Count("logs", filter=Q(logs__status=NotificationLog.Status.DELIVERED)),
        "n_not_delivered": Count("logs", filter=Q(logs__status__in=NotificationLog.NOT_DELIVERED)),
        "n_queued": Count("logs", filter=Q(logs__status=NotificationLog.Status.QUEUED)),
    }
    found = []
    for model, ch in ((EmailBatch, Channel.EMAIL), (SmsBatch, Channel.SMS)):
        if channel and channel != ch:
            continue
        qs = model.objects.select_related("created_by").annotate(**counts)
        if q:
            match = Q(name__icontains=q) | Q(batch_code__icontains=q) | Q(body__icontains=q)
            if model is EmailBatch:
                match |= Q(subject__icontains=q)
            qs = qs.filter(match)
        if problems:
            qs = qs.filter(n_not_delivered__gt=0)
        found.append(qs.order_by("-created_at")[:limit])
    return sorted(chain(*found), key=lambda b: b.created_at, reverse=True)[:limit]


def recent_batches(limit=200):
    """(batch_code, label) pairs for pickers, newest first."""
    rows = [*EmailBatch.objects.values_list("batch_code", "name", "created_at")[:limit],
            *SmsBatch.objects.values_list("batch_code", "name", "created_at")[:limit]]
    rows.sort(key=lambda r: r[2], reverse=True)
    return [(code, f"{name} ({code})" if name else code) for code, name, _ in rows[:limit]]


def student_ids_in_batch(code, statuses=None):
    """IDs of the students a batch was addressed to (optionally only with these delivery statuses).
    Returned as a subquery for filtering students by message history."""
    fk = "email_batch__batch_code" if str(code).startswith("EB-") else "sms_batch__batch_code"
    logs = NotificationLog.objects.filter(**{fk: code}, student__isnull=False)
    if statuses:
        logs = logs.filter(status__in=statuses)
    return logs.values("student_id")


# ---- Delivery webhooks ------------------------------------------------------ #
def verify_webhook_token(token):
    expected = settings.NOTIFICATIONS["WEBHOOK_TOKEN"]
    return bool(expected) and hmac.compare_digest(str(token), expected)


# Brevo transactional webhook events -> our statuses. Others (request, opened, click, soft_bounce,
# deferred, spam, unsubscribed…) don't change delivery status: Brevo retries soft bounces itself.
BREVO_EVENTS = {"delivered": "delivered", "hard_bounce": "bounced", "invalid_email": "bounced",
                "blocked": "failed", "error": "failed"}


def normalize_event(event):
    """(message_id, status, error) from a webhook event: our generic format
    {"message_id", "status", "error"} or Brevo's {"event", "message-id", "reason"}."""
    if "event" in event:  # Brevo
        return (str(event.get("message-id") or event.get("message_id") or ""),
                BREVO_EVENTS.get(str(event.get("event", "")).lower(), ""), str(event.get("reason") or ""))
    return str(event.get("message_id", "")), str(event.get("status", "")).lower(), str(event.get("error", ""))


def apply_delivery_event(channel, provider_message_id, status, error=""):
    mapping = {"delivered": NotificationLog.Status.DELIVERED, "bounced": NotificationLog.Status.BOUNCED,
               "failed": NotificationLog.Status.FAILED}
    provider_message_id = provider_message_id.strip().strip("<>")
    if status not in mapping or not provider_message_id:
        return 0
    return NotificationLog.objects.filter(channel=channel, provider_message_id=provider_message_id).update(
        status=mapping[status], error=error[:500], status_updated_at=timezone.now())
