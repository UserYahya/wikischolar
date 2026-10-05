from django.conf import settings

from . import turnstile


def platform(request):
    ws = settings.WIKISCHOLAR
    site = ws["SITE_URL"].rstrip("/")
    ctx = {"CONTACT_EMAIL": ws["CONTACT_EMAIL"], "POLICY_URL": ws["POLICY_URL"],
           "SITE_URL": site, "SITE_HOST": site.split("://", 1)[-1],
           "TURNSTILE_SITE_KEY": turnstile.site_key(), "TURNSTILE_SCRIPT": turnstile.SCRIPT_URL}
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        from .registry import nav_for, nav_groups_for
        ctx["NAV"] = nav_for(user)
        ctx["NAV_GROUPS"] = nav_groups_for(user)
    return ctx
