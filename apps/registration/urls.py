from django.urls import path

from . import views

app_name = "registration"
urlpatterns = [
    path("", views.register_page, name="register"),
    path("api/registration/email/check/", views.check_email, name="check_email"),
    path("api/registration/email/send-otp/", views.send_otp, name="send_otp"),
    path("api/registration/email/verify-otp/", views.verify_otp, name="verify_otp"),
    path("api/registration/submit/", views.submit, name="submit"),
]
