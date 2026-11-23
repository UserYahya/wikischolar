"""The "Email the student about this change" box on the dashboard's student editor, and the
"Registration details changed" system email it sends."""
from unittest import mock

from django.core import mail

from apps.core.models import AuditLog
from apps.notifications.models import NotificationLog
from apps.notifications.providers.base import SendResult
from apps.reference.models import School
from apps.registration.models import EditHistory, Student

from .base import WSTestCase

KEY = "registration.changed"


class ChangeNoticeTests(WSTestCase):
    def setUp(self):
        super().setUp()
        self.wsid = self.register()["wikischolar_id"]
        self.url = f"/dashboard/students/{self.wsid}/edit/"
        self.client.force_login(self.admin)
        mail.outbox.clear()

    def student(self):
        return Student.objects.get(wikischolar_id=self.wsid)

    def edit(self, notify=True, **over):
        st = self.student()
        data = {"student_name": st.student_name, "gender": st.gender,
                "guardian_name": st.guardian_name, "guardian_relation": st.guardian_relation,
                "guardian_relation_other": st.guardian_relation_other,
                "district": st.district_id, "thana": st.thana_id, "school": st.school_id,
                "current_class": st.current_class, "class_roll": st.class_roll, "student_id_sid": st.student_id_sid,
                "section": st.section, "phone": st.phone, "email": st.email, "updates_opt_in": "on",
                "reason": "Guardian called: wrong class"}
        if notify:
            data["notify_student"] = "on"
        data.update(over)
        r = self.client.post(self.url, data)
        self.assertEqual(r.status_code, 302, r.content[:2000])
        return r, [str(m) for m in r.wsgi_request._messages]

    def notices(self):
        return NotificationLog.objects.filter(kind=NotificationLog.Kind.CHANGE)

    def test_checkbox_is_on_the_edit_page_and_unticked(self):
        page = self.client.get(self.url).content.decode()
        self.assertIn('name="notify_student"', page)
        self.assertNotIn('name="notify_student" checked', page)
        self.assertIn("Email the student about this change", page)
        self.assertLess(page.index('name="notify_student"'), page.index("Save changes"))

    def test_unticked_saves_without_email(self):
        _, flashes = self.edit(notify=False, current_class="9")
        self.assertEqual(self.student().current_class, "9")
        self.assertEqual(mail.outbox, [])
        self.assertFalse(self.notices().exists())
        self.assertIn("Saved 1 change(s).", flashes)

    def test_ticked_emails_what_changed(self):
        _, flashes = self.edit(current_class="9", section="B")
        self.assertEqual(len(mail.outbox), 1)
        m = mail.outbox[0]
        self.assertEqual(m.to, ["rahim@gmail.com"])
        self.assertEqual(m.subject, f"Your WikiScholar details were updated: {self.wsid}")
        self.assertIn("Dear Rahim Uddin", m.body)
        self.assertIn("Class: Class 9 (was: Class 8)", m.body)
        self.assertIn("Section: B (was: not given)", m.body)
        self.assertIn("Your registration details now:", m.body)
        self.assertIn("School: TONGI GOVERNMENT HIGH SCHOOL", m.body)  # the full details, with names
        self.assertNotIn("wrong class", m.body)  # the reason is for staff only
        html = m.alternatives[0][0]
        self.assertIn("Class 9", html)
        self.assertIn("was: Class 8", html)
        self.assertNotIn("{changes}", html)
        log = self.notices().get()
        self.assertEqual((log.status, log.destination, log.student.wikischolar_id), ("sent", "rahim@gmail.com", self.wsid))
        audit = AuditLog.objects.get(action="student.notified")
        self.assertEqual((audit.actor, audit.meta["fields"], audit.meta["status"]),
                         (self.admin, ["current_class", "section"], "sent"))
        self.assertIn("Saved 2 change(s) and emailed the student at rahim@gmail.com.", flashes)
        # the notice shows on the student's page with the other messages
        self.assertContains(self.client.get(f"/dashboard/students/{self.wsid}/"), "Change notice")

    def test_names_not_ids(self):
        other = School.objects.create(name="Kaliakair Pilot High School", district=self.gazipur,
                                      thana=self.kaliakair, verification_status="verified", source="admin")
        self.edit(thana=self.kaliakair.pk, school=other.pk, updates_opt_in="")
        body = mail.outbox[0].body
        self.assertIn("Thana / Upazila: Kaliakair (was: Tongi)", body)
        self.assertIn("School: KALIAKAIR PILOT HIGH SCHOOL (was: TONGI GOVERNMENT HIGH SCHOOL)", body)
        self.assertIn("Email updates: No (was: Yes)", body)
        self.assertNotIn(f"(was: {self.school.pk})", body)

    def test_new_email_address_gets_it_and_old_one_does_not(self):
        _, flashes = self.edit(email="rahim.new@gmail.com")
        self.assertEqual([m.to for m in mail.outbox], [["rahim.new@gmail.com"]])
        self.assertIn("Email: rahim.new@gmail.com (was: rahim@gmail.com)", mail.outbox[0].body)
        self.assertIn("Saved 1 change(s) and emailed the student at rahim.new@gmail.com.", flashes)

    def test_relation_to_other_is_one_line(self):
        self.edit(guardian_relation="other", guardian_relation_other="Uncle")
        self.assertEqual(EditHistory.objects.filter(student__wikischolar_id=self.wsid).count(), 2)
        body = mail.outbox[0].body
        self.assertEqual(body.count("Guardian's relation:"), 1)
        self.assertIn("Guardian's relation: Uncle (was: Father)", body)

    def test_nothing_changed_sends_nothing(self):
        _, flashes = self.edit()
        self.assertEqual(mail.outbox, [])
        self.assertFalse(self.notices().exists())
        self.assertIn("Nothing changed. No email was sent.", flashes)

    def test_failed_email_keeps_the_change_and_warns(self):
        with mock.patch("apps.notifications.providers.email.DjangoMailProvider.send",
                        return_value=SendResult(ok=False, error="550 sender not verified")):
            _, flashes = self.edit(current_class="9")
        self.assertEqual(self.student().current_class, "9")
        self.assertEqual(self.notices().get().status, "failed")
        self.assertTrue(any("could not be sent: 550 sender not verified" in f for f in flashes), flashes)
        self.assertEqual(AuditLog.objects.get(action="student.notified").meta["status"], "failed")

    def test_email_set_up_problem_keeps_the_change_and_warns(self):
        with mock.patch("apps.notifications.services.provider_for", side_effect=ValueError("bad key")), \
                self.assertLogs("apps.registration.services", "ERROR"):
            _, flashes = self.edit(current_class="9")
        self.assertEqual(self.student().current_class, "9")
        self.assertTrue(any("could not be sent" in f for f in flashes), flashes)
        self.assertEqual(AuditLog.objects.get(action="student.notified").meta["status"], "failed")

    def test_viewer_cannot_edit_or_notify(self):
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.post(self.url, {"notify_student": "on"}).status_code, 403)
        self.assertEqual(mail.outbox, [])


class ChangeNoticeWordingTests(WSTestCase):
    url = "/dashboard/settings/system-emails/"

    def setUp(self):
        super().setUp()
        self.client.force_login(self.super)

    def save(self, subject, body):
        return self.client.post(self.url, {"op": "save", "key": KEY, f"{KEY}-subject": subject, f"{KEY}-body": body})

    def test_listed_with_a_preview(self):
        page = self.client.get(self.url).content.decode()
        self.assertIn("Registration details changed", page)
        self.assertIn("Class: Class 8 (was: Class 7)", page)  # sample data in the preview
        self.assertIn("{changes}", page)

    def test_changes_placeholder_is_required(self):
        r = self.save("Updated", "Dear {student_name}")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "must contain {changes}")

    def test_saved_wording_is_used(self):
        r = self.save("Record updated {wikischolar_id}", "Hello {student_name}\n\n{changes}\n\nThanks")
        self.assertEqual(r.status_code, 302)
        wsid = self.register()["wikischolar_id"]
        st = Student.objects.get(wikischolar_id=wsid)
        mail.outbox.clear()
        self.client.force_login(self.admin)
        self.client.post(f"/dashboard/students/{wsid}/edit/", {
            "student_name": st.student_name, "gender": st.gender, "guardian_name": st.guardian_name,
            "guardian_relation": st.guardian_relation, "district": st.district_id, "thana": st.thana_id,
            "school": st.school_id, "current_class": "10", "class_roll": st.class_roll, "phone": st.phone,
            "email": st.email, "updates_opt_in": "on", "notify_student": "on"})
        m = mail.outbox[0]
        self.assertEqual(m.subject, f"Record updated {wsid}")
        self.assertEqual(m.body, "Hello Rahim Uddin\n\nClass: Class 10 (was: Class 8)\n\nThanks")
