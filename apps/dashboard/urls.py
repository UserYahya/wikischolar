from django.urls import path

from .views import accounts, home, messaging, reference, settings, students

app_name = "dashboard"
urlpatterns = [
    path("login/", accounts.login_view, name="login"),
    path("logout/", accounts.logout_view, name="logout"),
    path("", home.home, name="home"),

    path("students/", students.student_list, name="students"),
    path("students/export.csv", students.student_export, name="students_export"),
    path("students/archived/", students.archived, name="archived"),
    path("students/<str:wsid>/", students.student_detail, name="student"),
    path("students/<str:wsid>/edit/", students.student_edit, name="student_edit"),
    path("students/<str:wsid>/archive/", students.student_archive, name="student_archive"),
    path("students/<str:wsid>/restore/", students.student_restore, name="student_restore"),

    path("messages/", messaging.batch_list, name="batches"),
    path("messages/compose/", messaging.compose, name="compose"),
    path("messages/<str:code>/", messaging.batch_detail, name="batch"),
    path("messages/<str:code>/recipients.csv", messaging.batch_recipients_csv, name="batch_recipients_csv"),
    path("messages/<str:code>/send/", messaging.send_remaining, name="batch_send"),
    path("messages/<str:code>/resend/", messaging.resend_failed, name="batch_resend"),

    path("schools/", reference.school_list, name="schools"),
    path("schools/add/", reference.school_add, name="school_add"),
    path("schools/import/", reference.school_import, name="school_import"),
    path("schools/import/template.csv", reference.school_import_template, name="school_import_template"),
    path("schools/duplicates/", reference.duplicates, name="duplicates"),
    path("schools/merge/", reference.merge, name="merge"),
    path("schools/<int:pk>/", reference.school_detail, name="school"),
    path("locations/", reference.locations, name="locations"),
    path("locations/districts/<int:pk>/", reference.district_detail, name="district"),

    path("audit/", accounts.audit_log, name="audit"),
    path("admins/", accounts.admin_list, name="admins"),
    path("admins/<int:pk>/", accounts.admin_update, name="admin_update"),
    path("settings/email/", settings.email_settings, name="email_settings"),
    path("settings/system-emails/", settings.system_emails, name="system_emails"),
]
