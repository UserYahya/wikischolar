from django.apps import AppConfig


class DashboardConfig(AppConfig):
    name = "apps.dashboard"
    label = "dashboard"
    verbose_name = "Admin Dashboard"

    def ready(self):
        from apps.core.registry import register_nav as nav
        nav("Overview", "dashboard:home", "students.view", 10, "dashboard")
        nav("All students", "dashboard:students", "students.view", 20, "registration", group="Students")
        nav("Archived records", "dashboard:archived", "students.delete", 21, "registration", group="Students")
        nav("Saved searches", "dashboard:searches", "students.view", 22, "dashboard", group="Students")
        nav("Schools", "dashboard:schools", "schools.view", 30, "reference", group="Schools & places")
        nav("Duplicate schools", "dashboard:duplicates", "schools.merge", 31, "reference", group="Schools & places")
        nav("Regions & districts", "dashboard:locations", "reference.view", 32, "reference", group="Schools & places")
        nav("Messages", "dashboard:batches", "messages.view", 40, "notifications", group="Messaging")
        nav("System emails", "dashboard:system_emails", "settings.manage", 41, "notifications", group="Messaging")
        nav("Email & SMS settings", "dashboard:email_settings", "settings.manage", 42, "notifications",
            group="Messaging")
        nav("Admins", "dashboard:admins", "admins.manage", 50, "core", group="Administration")
        nav("Audit log", "dashboard:audit", "audit.view", 51, "core", group="Administration")
