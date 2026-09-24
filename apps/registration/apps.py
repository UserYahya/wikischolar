from django.apps import AppConfig


class RegistrationConfig(AppConfig):
    name = "apps.registration"
    label = "registration"
    verbose_name = "Registration"

    def ready(self):
        from . import emails
        emails.register()  # OTP + confirmation wording, editable on Dashboard -> System emails
