"""The whole site is English now (LANGUAGE_CODE = "en"). This keeps the dashboard pinned to
English even if a later module switches the default language for its own public pages."""
from django.utils import translation


class DashboardLanguageMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith("/dashboard/"):
            with translation.override("en"):
                response = self.get_response(request)
            response.headers.setdefault("Content-Language", "en")
            return response
        return self.get_response(request)
