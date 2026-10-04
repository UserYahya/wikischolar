from django.conf import settings


def platform(request):
    ws = settings.WIKISCHOLAR
    site = ws["SITE_URL"].rstrip("/")
    ctx = {"CONTACT_EMAIL": ws["CONTACT_EMAIL"], "POLICY_URL": ws["POLICY_URL"],
           "SITE_URL": site, "SITE_HOST": site.split("://", 1)[-1]}
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        from .registry import nav_for, nav_groups_for
        ctx["NAV"] = nav_for(user)
        ctx["NAV_GROUPS"] = nav_groups_for(user)
    return ctx
