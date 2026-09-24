from django.conf import settings
from django.core.mail import EmailMessage
from django.core.mail.message import make_msgid

from .base import Provider, SendResult


def reply_to_address(cfg):
    """Reply-to for every outgoing email: the one saved in Email settings, else WS_REPLY_TO
    (info@wikischolar.bd by default). Empty means replies go to the From address."""
    return (cfg.reply_to if cfg and cfg.reply_to else settings.WIKISCHOLAR["REPLY_TO"]) or ""


class DjangoMailProvider(Provider):
    """Sends through the credentials a Super Admin saved on Dashboard -> Email settings
    (Brevo / Gmail / any SMTP) when active; otherwise Django's EMAIL_BACKEND from env."""
    name = "django-mail"

    def send(self, destination, body, subject=""):
        from ..models import EmailSettings
        cfg = EmailSettings.active()
        from_email = cfg.from_header if cfg else settings.DEFAULT_FROM_EMAIL
        domain = (cfg.from_email if cfg else from_email).rsplit("@", 1)[-1].strip("> ") or "wikischolar.bd"
        msg_id = make_msgid(domain=domain)
        reply_to = reply_to_address(cfg)
        msg = EmailMessage(subject=subject, body=body, from_email=from_email, to=[destination],
                           headers={"Message-ID": msg_id}, connection=cfg.connection() if cfg else None,
                           reply_to=[reply_to] if reply_to else None)
        try:
            msg.send(fail_silently=False)
        except Exception as exc:  # isolate provider failures from the caller
            return SendResult(ok=False, error=str(exc)[:500])
        # Brevo's HTTPS API assigns its own message ID (used by its delivery webhooks); SMTP keeps ours.
        provider_id = getattr(msg, "provider_message_id", "") or msg_id
        return SendResult(ok=True, provider_message_id=provider_id.strip("<>"))
