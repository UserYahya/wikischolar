from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.dispatch import receiver

from . import audit


@receiver(user_logged_in)
def on_login(sender, request, user, **kwargs):
    audit.record("admin.login", request=request, actor=user, entity=user)


@receiver(user_logged_out)
def on_logout(sender, request, user, **kwargs):
    if user:
        audit.record("admin.logout", request=request, actor=user, entity=user)


@receiver(user_login_failed)
def on_login_failed(sender, credentials, request=None, **kwargs):
    audit.record("admin.login_failed", request=request, actor_type="system",
                 meta={"email": credentials.get("username", "")[:254]})
