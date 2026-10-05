from django.shortcuts import redirect
from django.templatetags.static import static
from django.urls import include, path


def favicon(request):
    """Browsers and crawlers ask for /favicon.ico directly; pages link the PNG icons (templates/_favicons.html)."""
    return redirect(static("img/favicon-32.png"))


urlpatterns = [
    path("favicon.ico", favicon),
    path("", include("apps.registration.urls")),
    path("api/reference/", include("apps.reference.urls")),
    path("notifications/", include("apps.notifications.urls")),
    path("dashboard/", include("apps.dashboard.urls")),
]
