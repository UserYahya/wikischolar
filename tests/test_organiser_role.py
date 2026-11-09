"""Organiser: a dashboard role that sees the Overview's statistics only: no student records, names,
contact details, schools, messages or settings."""
from apps.core.models import Admin, Role
from apps.core.permissions import ROLE_PERMISSIONS

from .base import WSTestCase


class OrganiserRoleTests(WSTestCase):
    def setUp(self):
        super().setUp()
        self.s = self.register(student_name="Rahim Uddin", email="rahim@gmail.com")
        self.organiser = Admin.objects.create_user(email="organiser@ws.test", password="x-Strong-pass-123",
                                                   full_name="Organiser", role=Role.ORGANISER)
        self.client.force_login(self.organiser)

    def test_overview_shows_numbers_without_personal_data_or_links(self):
        r = self.client.get("/dashboard/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context["total"], 1)
        page = r.content.decode()
        self.assertIn("registered students", page)
        self.assertIn("Gazipur", page)  # top districts, by name only
        for private in ("Rahim Uddin", "rahim@gmail.com", "01712345678", self.s["wikischolar_id"], "Karim Uddin"):
            self.assertNotIn(private, page)
        for link in ("/dashboard/students/", "/dashboard/schools/", "/dashboard/locations/", "/dashboard/messages/"):
            self.assertNotIn(f'href="{link}', page)
        # the menu offers the Overview and nothing else
        self.assertEqual([i.url_name for i in r.context["NAV"]], ["dashboard:home"])

    def test_every_other_page_is_refused(self):
        wsid = self.s["wikischolar_id"]
        urls = ["/dashboard/students/", f"/dashboard/students/{wsid}/", f"/dashboard/students/{wsid}/edit/",
                "/dashboard/students/export.csv", "/dashboard/students/archived/", "/dashboard/searches/",
                "/dashboard/schools/", "/dashboard/schools/export.csv", f"/dashboard/schools/{self.school.pk}/",
                "/dashboard/schools/duplicates/", "/dashboard/locations/", "/dashboard/messages/",
                "/dashboard/messages/compose/", "/dashboard/audit/", "/dashboard/admins/",
                "/dashboard/settings/email/", "/dashboard/settings/system-emails/"]
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 403, url)
        self.assertEqual(self.client.get("/dashboard/account/password/").status_code, 200)  # own password

    def test_permissions_are_statistics_only(self):
        self.assertEqual(ROLE_PERMISSIONS["organiser"], {"stats.view"})
        for role in ("viewer", "admin", "super_admin"):  # every other role keeps the Overview
            self.assertIn("stats.view", ROLE_PERMISSIONS[role])

    def test_super_admin_can_create_an_organiser(self):
        self.client.force_login(self.super)
        r = self.client.get("/dashboard/admins/")
        self.assertContains(r, "Organiser (statistics only)")
        self.client.post("/dashboard/admins/", {"full_name": "Event Organiser", "email": "events@ws.test",
                                                "role": "organiser", "password": "x-Strong-pass-123"})
        self.assertEqual(Admin.objects.get(email="events@ws.test").role, "organiser")

    def test_other_roles_still_see_overview_links(self):
        self.client.force_login(self.viewer)
        page = self.client.get("/dashboard/").content.decode()
        self.assertIn('href="/dashboard/students/?district=', page)
