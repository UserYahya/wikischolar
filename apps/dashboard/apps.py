from django.apps import AppConfig


class DashboardConfig(AppConfig):
    name = "apps.dashboard"
    label = "dashboard"
    verbose_name = "Admin Dashboard"

    def ready(self):
        from apps.core.registry import register_nav as nav
        nav("Overview", "dashboard:home", "students.view", 10, "dashboard")
        nav("Students", "dashboard:students", "students.view", 20, "registration")
        nav("Messages", "dashboard:batches", "messages.view", 30, "notifications")
        nav("Schools", "dashboard:schools", "schools.view", 40, "reference")
        nav("Duplicate schools", "dashboard:duplicates", "schools.merge", 45, "reference")
        nav("Regions & districts", "dashboard:locations", "reference.view", 50, "reference")
        nav("Archived records", "dashboard:archived", "students.delete", 60, "registration")
        nav("Audit log", "dashboard:audit", "audit.view", 70, "core")
        nav("Admins", "dashboard:admins", "admins.manage", 80, "core")
        nav("Email & SMS settings", "dashboard:email_settings", "settings.manage", 90, "notifications")
        nav("System emails", "dashboard:system_emails", "settings.manage", 91, "notifications")
