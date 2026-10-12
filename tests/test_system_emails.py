"""Guardian declaration on the form, and system emails (OTP, confirmation) editable by a Super Admin."""
import re

from django.core import mail
from django.db import IntegrityError, connection, transaction

from apps.core.models import AuditLog
from apps.notifications.models import EmailTemplate
from apps.registration.models import Student

from .base import WSTestCase

OTP_FIELDS = "registration.otp"
CONF_FIELDS = "registration.confirmation"


class GuardianDeclarationTests(WSTestCase):
    def submit(self, **over):
        vid = self.verify_email()
        mail.outbox.clear()
        with self.captureOnCommitCallbacks(execute=True):
            r = self.post_json("/api/registration/submit/", self.payload(vid, **over))
        self.assertEqual(r.status_code, 201, r.content)
        return r.json()["summary"], Student.objects.get(wikischolar_id=r.json()["summary"]["wikischolar_id"])

    def test_required_checkbox_is_at_the_start_of_the_form(self):
        page = self.client.get("/").content.decode()
        self.assertIn('name="guardian_declaration" id="guardian_declaration" required', page)
        self.assertIn("I am the <strong>guardian</strong> of the student named below", page)
        self.assertNotIn("guardian (parent)", page)
        self.assertNotIn("Leave this unticked", page)
        self.assertLess(page.index('name="guardian_declaration"'), page.index('name="student_name"'))

    def test_declaration_is_mandatory(self):
        vid = self.verify_email()
        for value in (False, None):
            payload = self.payload(vid, guardian_declaration=value)
            if value is None:
                payload.pop("guardian_declaration")
            r = self.post_json("/api/registration/submit/", payload)
            self.assertEqual(r.status_code, 400)
            self.assertIn("guardian declaration", r.json()["errors"]["guardian_declaration"][0])
        self.assertFalse(Student.objects.exists())

    def test_guardian_declaration_is_recorded(self):
        s, st = self.submit()
        self.assertEqual(st.filled_by, "guardian")
        self.assertIsNotNone(st.guardian_declared_at)
        self.assertEqual(s["filled_by"], "The student's guardian")
        self.assertIn("Form filled in by: The student's guardian", mail.outbox[-1].body)
        log = AuditLog.objects.get(action="student.registered", entity_id=st.wikischolar_id)
        self.assertEqual(log.meta["filled_by"], "guardian")

    def test_database_keeps_declaration_consistent(self):
        self.submit()
        with self.assertRaises(IntegrityError):
            with transaction.atomic(), connection.cursor() as c:
                c.execute("UPDATE students SET guardian_declared_at = NULL")  # guardian without declaration time

    def test_dashboard_shows_filters_and_exports_it(self):
        _, guardian_st = self.submit()
        # a registration from before the declaration was introduced
        legacy = self.register(email="old@gmail.com")["wikischolar_id"]
        Student.objects.filter(wikischolar_id=legacy).update(filled_by="student", guardian_declared_at=None)
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(f"/dashboard/students/{guardian_st.wikischolar_id}/"), "guardian declared")
        r = self.client.get("/dashboard/students/", {"filled_by": "guardian"})
        self.assertEqual([s.wikischolar_id for s in r.context["page"]], [guardian_st.wikischolar_id])
        r = self.client.get("/dashboard/students/", {"filled_by": "student"})
        self.assertEqual(r.context["count"], 1)
        body = b"".join(self.client.get("/dashboard/students/export.csv").streaming_content).decode("utf-8-sig")
        header = body.splitlines()[0].split(",")
        self.assertIn("filled_by", header)
        self.assertIn("guardian_declared_at", header)
        self.assertIn(",guardian,", body)


class SystemEmailTests(WSTestCase):
    url = "/dashboard/settings/system-emails/"

    def save(self, key, subject, body):
        return self.client.post(self.url, {"op": "save", "key": key, f"{key}-subject": subject, f"{key}-body": body})

    def test_only_super_admin(self):
        for user, code in [(self.viewer, 403), (self.admin, 403), (self.super, 200)]:
            self.client.force_login(user)
            self.assertEqual(self.client.get(self.url).status_code, code)

    def test_page_lists_both_emails_with_defaults_and_preview(self):
        self.client.force_login(self.super)
        r = self.client.get(self.url)
        self.assertEqual([c["email"].key for c in r.context["cards"]], [OTP_FIELDS, CONF_FIELDS])
        self.assertContains(r, "Your WikiScholar verification code is:")  # preview with sample data
        self.assertContains(r, "123456")
        self.assertContains(r, 'class="email-preview"')
        self.assertContains(r, "WikiScholar registration complete: WS-2027-000123")
        self.assertContains(r, "Default text")

    def test_custom_otp_email_is_used(self):
        self.client.force_login(self.super)
        r = self.save(OTP_FIELDS, "Code: {code}", "Hello!\n\nYour code is {code} (valid {minutes} min).\nআপনার কোড")
        self.assertEqual(r.status_code, 302)
        self.client.logout()
        self.client.get("/")
        mail.outbox.clear()
        self.post_json("/api/registration/email/send-otp/", {"email": "rahim@gmail.com"})
        msg = mail.outbox[-1]
        code = re.search(r"Your code is (\d{6})", msg.body).group(1)
        self.assertEqual(msg.subject, f"Code: {code}")
        self.assertIn("(valid 10 min)", msg.body)
        self.assertIn("আপনার কোড", msg.body)  # the wording itself may be in any language
        log = AuditLog.objects.get(action="settings.system_email_updated")
        self.assertEqual(log.before["subject"], "Your WikiScholar verification code")
        self.assertEqual(log.after["subject"], "Code: {code}")

    def test_otp_without_code_or_with_unknown_placeholder_is_refused(self):
        self.client.force_login(self.super)
        r = self.save(OTP_FIELDS, "Your code", "Welcome, your code arrives soon.")
        self.assertEqual(r.status_code, 200)
        self.assertIn("must contain {code}", str(r.context["cards"][0]["form"].errors))
        r = self.save(OTP_FIELDS, "Your code", "Code {code}, valid {minuts} minutes")
        self.assertIn("Unknown placeholder {minuts}", str(r.context["cards"][0]["form"].errors))
        self.assertFalse(EmailTemplate.objects.exists())

    def test_custom_confirmation_email_is_used(self):
        self.client.force_login(self.super)
        self.save(CONF_FIELDS, "Welcome {student_name} ({wikischolar_id})",
                  "Hi {student_name}!\nID: {wikischolar_id}\nSchool: {school}\n\n{details}\n")
        self.client.logout()
        vid = self.verify_email()
        mail.outbox.clear()
        with self.captureOnCommitCallbacks(execute=True):
            r = self.post_json("/api/registration/submit/", self.payload(vid))
        wsid = r.json()["summary"]["wikischolar_id"]
        msg = mail.outbox[-1]
        self.assertEqual(msg.subject, f"Welcome Rahim Uddin ({wsid})")
        self.assertIn(f"ID: {wsid}\nSchool: TONGI GOVERNMENT HIGH SCHOOL", msg.body)
        self.assertIn("Class: Class 8", msg.body)  # from {details}
        self.assertEqual(msg.reply_to, ["info@wikischolar.bd"])

    def test_reset_goes_back_to_default_without_deleting(self):
        self.client.force_login(self.super)
        self.save(OTP_FIELDS, "Code {code}", "Code {code}")
        self.client.post(self.url, {"op": "reset", "key": OTP_FIELDS})
        row = EmailTemplate.objects.get(key=OTP_FIELDS)
        self.assertFalse(row.is_customized)
        self.assertTrue(AuditLog.objects.filter(action="settings.system_email_reset",
                                                before__subject="Code {code}").exists())
        self.client.get("/")
        mail.outbox.clear()
        self.post_json("/api/registration/email/send-otp/", {"email": "rahim@gmail.com"})
        self.assertEqual(mail.outbox[-1].subject, "Your WikiScholar verification code")

    def test_send_test_uses_sample_data(self):
        self.client.force_login(self.super)
        mail.outbox.clear()
        r = self.client.post(self.url, {"op": "test", "key": CONF_FIELDS}, follow=True)
        self.assertContains(r, "Test of “Registration confirmation” sent to super@ws.test")
        msg = mail.outbox[-1]
        self.assertEqual((msg.to, msg.subject), (["super@ws.test"], "[TEST] WikiScholar registration complete: WS-2027-000123"))
        self.assertIn("Form filled in by: The student's guardian", msg.body)
        self.assertTrue(AuditLog.objects.filter(action="settings.system_email_tested", entity_id=CONF_FIELDS).exists())

    def test_menu_item_for_super_admin(self):
        self.client.force_login(self.super)
        self.assertContains(self.client.get("/dashboard/"), "System emails")
        self.client.force_login(self.admin)
        self.assertNotContains(self.client.get("/dashboard/"), "System emails")
