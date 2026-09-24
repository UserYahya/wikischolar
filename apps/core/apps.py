from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = "apps.core"
    label = "core"
    verbose_name = "Core / Shared"

    def ready(self):
        from . import signals  # noqa: F401  (login/logout auditing)
