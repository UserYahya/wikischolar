"""Youth Safety Policy 4.5: an optional checkbox on the last step lets the guardian allow photos of the
child at offline events. Stored with its date, shown and editable (withdrawal) on the dashboard."""
import csv
import io
import json

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.dashboard import advanced
from apps.registration.models import EditHistory, Student

from .base import WSTestCase


class PhotoConsentTests(WSTestCase):
    def student(self, summary):
        return Student.objects.get(wikischolar_id=summary["wikischolar_id"])

    def test_checkbox_on_the_last_step_without_saying_optional(self):
        page = self.client.get("/").content.decode()
        self.assertIn('name="photo_consent"', page)
        self.assertIn("I give permission for my child to be photographed at offline events", page)
        self.assertIn("৪.৫ অনুচ্ছেদ অনুযায়ী অফলাইন ইভেন্টে আমার সন্তানের ছবি তোলার অনুমতি দিচ্ছি।", page)
        box = page[page.index('name="photo_consent"'):page.index('name="updates_opt_in"')]
        self.assertNotIn("required", box)
        self.assertNotIn("optional", box.lower())
        self.assertNotIn("ঐচ্ছিক", box)

    def test_stored_with_its_date_when_ticked(self):
        given = self.student(self.register(photo_consent=True))
        self.assertTrue(given.photo_consent)
        self.assertLess((timezone.now() - given.photo_consent_at).total_seconds(), 60)
        # not ticked (or an older browser that doesn't send it): registration still works
        payload_without = self.student(self.register(email="no-photo@gmail.com", phone="01812345678"))
        self.assertEqual((payload_without.photo_consent, payload_without.photo_consent_at), (False, None))

    def test_database_keeps_flag_and_date_together(self):
        s = self.student(self.register())
        with self.assertRaises(IntegrityError), transaction.atomic():
            Student.objects.filter(pk=s.pk).update(photo_consent=True)  # without a date
        with self.assertRaises(IntegrityError), transaction.atomic():
            Student.objects.filter(pk=s.pk).update(photo_consent_at=timezone.now())  # date without permission

    def test_dashboard_page_filter_search_and_export(self):
        yes = self.student(self.register(photo_consent=True))
        no = self.student(self.register(email="no-photo@gmail.com", phone="01812345678"))
        self.client.force_login(self.viewer)
        self.assertContains(self.client.get(f"/dashboard/students/{yes.wikischolar_id}/"), "Permitted")
        self.assertContains(self.client.get(f"/dashboard/students/{no.wikischolar_id}/"), "Not permitted")
        r = self.client.get("/dashboard/students/?photo=1")
        self.assertEqual([s.pk for s in r.context["page"]], [yes.pk])
        q, problems, _ = advanced.parse("students", json.dumps(
            {"match": "all", "groups": [{"match": "all", "conditions": [{"field": "photo_consent", "op": "no"}]}]}))
        self.assertEqual((set(Student.objects.filter(q).values_list("pk", flat=True)), problems), ({no.pk}, []))
        self.client.force_login(self.admin)  # export needs students.export
        r = self.client.get("/dashboard/students/export.csv")
        rows = {row["wikischolar_id"]: row for row in
                csv.DictReader(io.StringIO(b"".join(r.streaming_content).decode("utf-8-sig")))}
        self.assertEqual(rows[yes.wikischolar_id]["photo_consent"], "True")
        self.assertTrue(rows[yes.wikischolar_id]["photo_consent_at"])
        self.assertEqual((rows[no.wikischolar_id]["photo_consent"], rows[no.wikischolar_id]["photo_consent_at"]),
                         ("False", ""))

    def test_admin_records_withdrawal_and_later_permission(self):
        s = self.student(self.register(photo_consent=True))
        self.client.force_login(self.admin)
        data = {"student_name": s.student_name, "gender": s.gender, "guardian_name": s.guardian_name,
                "guardian_relation": s.guardian_relation, "guardian_relation_other": "",
                "district": s.district_id, "thana": s.thana_id, "school": s.school_id,
                "current_class": s.current_class, "class_roll": s.class_roll, "student_id_sid": s.student_id_sid,
                "section": s.section, "phone": s.phone, "email": s.email, "updates_opt_in": "on",
                "reason": "Guardian withdrew photo permission by phone"}
        url = f"/dashboard/students/{s.wikischolar_id}/edit/"
        self.assertEqual(self.client.post(url, data).status_code, 302)  # checkbox left unticked
        s.refresh_from_db()
        self.assertEqual((s.photo_consent, s.photo_consent_at), (False, None))
        h = EditHistory.objects.get(student=s, field_name="photo_consent")
        self.assertEqual((h.old_value, h.new_value, h.reason),
                         (True, False, "Guardian withdrew photo permission by phone"))
        self.client.post(url, {**data, "photo_consent": "on", "reason": "Guardian allowed photos again"})
        s.refresh_from_db()
        self.assertTrue(s.photo_consent)
        self.assertIsNotNone(s.photo_consent_at)
