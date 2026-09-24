from django.urls import include, path

urlpatterns = [
    path("", include("apps.registration.urls")),
    path("api/reference/", include("apps.reference.urls")),
    path("notifications/", include("apps.notifications.urls")),
    path("dashboard/", include("apps.dashboard.urls")),
]
