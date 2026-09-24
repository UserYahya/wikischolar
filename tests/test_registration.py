import re

from django.conf import settings
from django.core import mail
from django.db import IntegrityError, connection, transaction
from django.test import override_settings

from apps.core.ids import next_wikischolar_id
from apps.core.models import AuditLog
from apps.reference.models import School
from apps.registration.models import EmailVerification, Student
from apps.registration.validators import normalize_phone, suggest_email_domain

from .base import WSTestCase


class RegistrationFlowTests(WSTestCase):
    def test_happy_path_assigns_id_region_and_audits(self):
        s = self.register()
        self.assertRegex(s["wikischolar_id"], r"^WS-\d{4}-\d{6}$")
        self.assertEqual(s["region"], "Dhaka")
        student = Student.objects.get(wikischolar_id=s["wikischolar_id"])
        self.assertEqual(student.school, self.school)
        self.assertEqual(student.school_resolution, "selected")
        self.assertIsNotNone(student.email_verified_at)
        self.assertIsNotNone(student.policy_consent_at)
        self.assertTrue(AuditLog.objects.filter(action="student.registered", entity_id=student.wikischolar_id).exists())
        ev = EmailVerification.objects.get(student=student)
        self.assertEqual(ev.status, "used")

    def test_id_uses_programme_year(self):
        self.assertTrue(self.register()["wikischolar_id"].startswith("WS-2027-"))
        with self.settings(WIKISCHOLAR={**settings.WIKISCHOLAR, "ID_YEAR": None}):
            from django.utils import timezone
            self.assertTrue(next_wikischolar_id().startswith(f"WS-{timezone.localdate().year}-"))

    def test_ids_are_sequential(self):
        a, b = next_wikischolar_id(), next_wikischolar_id()
        self.assertEqual(int(b[-6:]), int(a[-6:]) + 1)

    def test_roll_or_sid_required(self):
        vid = self.verify_email()
        r = self.post_json("/api/registration/submit/", self.payload(vid, class_roll="", student_id_sid=""))
        self.assertEqual(r.status_code, 400)
        self.assertIn("class_roll", r.json()["errors"])
        r = self.post_json("/api/registration/submit/", self.payload(vid, class_roll="", student_id_sid="SID-99"))
        self.assertEqual(r.status_code, 201)

    def test_phone_rules(self):
        self.assertEqual(normalize_phone("+880 1712-345678"), "01712345678")
        self.assertEqual(normalize_phone("০১৭১২৩৪৫৬৭৮"), "01712345678")
        vid = self.verify_email()
        for bad in ["01212345678", "0171234567", "abc"]:
            r = self.post_json("/api/registration/submit/", self.payload(vid, phone=bad))
            self.assertIn("phone", r.json().get("errors", {}), bad)

    def test_upazila_must_belong_to_district(self):
        vid = self.verify_email()
        r = self.post_json("/api/registration/submit/", self.payload(vid, upazila=self.sharsha.pk, school_id=None))
        self.assertIn("upazila", r.json()["errors"])

    def test_submit_requires_verified_email_in_this_session(self):
        vid = self.verify_email()
        other = self.client_class()
        other.get("/")
        r = self.post_json("/api/registration/submit/", self.payload(vid), other)
        self.assertEqual(r.json()["error"], "email_not_verified")
        # verified for a different address than submitted
        r = self.post_json("/api/registration/submit/", self.payload(vid, email="someone@gmail.com"))
        self.assertEqual(r.json()["error"], "email_not_verified")

    def test_consent_required(self):
        vid = self.verify_email()
        r = self.post_json("/api/registration/submit/", self.payload(vid, policy_consent=False))
        self.assertIn("policy_consent", r.json()["errors"])

    def test_only_classes_6_to_10(self):
        vid = self.verify_email()
        for bad in ["5", "11", "1"]:
            r = self.post_json("/api/registration/submit/", self.payload(vid, current_class=bad))
            self.assertEqual(r.status_code, 400, bad)
            self.assertIn("current_class", r.json()["errors"])
        r = self.post_json("/api/registration/submit/", self.payload(vid, current_class="10"))
        self.assertEqual(r.status_code, 201)

    def test_other_relation_needs_text(self):
        vid = self.verify_email()
        r = self.post_json("/api/registration/submit/", self.payload(vid, guardian_relation="other"))
        self.assertEqual(r.status_code, 400)
        self.assertIn("guardian_relation_other", r.json()["errors"])
        r = self.post_json("/api/registration/submit/", self.payload(
            vid, guardian_relation="other", guardian_relation_other="  Uncle "))
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()["summary"]["guardian"], "Karim Uddin (Uncle)")
        self.assertEqual(Student.objects.get().guardian_relation_other, "Uncle")

    def test_relation_text_dropped_unless_other(self):
        s = self.register(guardian_relation="mother", guardian_relation_other="Uncle")
        self.assertEqual(Student.objects.get(wikischolar_id=s["wikischolar_id"]).guardian_relation_other, "")

    def test_text_must_be_english(self):
        vid = self.verify_email()
        for field, value in [("student_name", "রহিম উদ্দিন"), ("guardian_name", "করিম"), ("school_name", "তাসলিমা একাডেমি"),
                             ("class_roll", "১২ক"), ("student_id_sid", "আইডি-৯")]:
            r = self.post_json("/api/registration/submit/", self.payload(vid, school_id=None, **{field: value}))
            self.assertEqual(r.status_code, 400, field)
            self.assertIn("English", r.json()["errors"][field][0], field)
        r = self.post_json("/api/registration/submit/", self.payload(
            vid, guardian_relation="other", guardian_relation_other="চাচা"))
        self.assertIn("guardian_relation_other", r.json()["errors"])
        self.assertFalse(Student.objects.exists())

    def test_bangla_digits_are_stored_as_english(self):
        s = self.register(class_roll="২৩", student_id_sid="SID-৪৫", phone="০১৭১২৩৪৫৬৭৮")
        st = Student.objects.get(wikischolar_id=s["wikischolar_id"])
        self.assertEqual((st.class_roll, st.student_id_sid, st.phone), ("23", "SID-45", "01712345678"))

    def test_messages_and_emails_are_english(self):
        vid = self.verify_email()
        r = self.post_json("/api/registration/submit/", self.payload(vid, class_roll="", student_id_sid=""))
        self.assertEqual(r.json()["errors"]["class_roll"], ["Fill in either the class roll or the student ID."])
        mail.outbox.clear()
        with self.captureOnCommitCallbacks(execute=True):  # the confirmation is sent after commit
            self.post_json("/api/registration/submit/", self.payload(vid))
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[-1].subject[:34], "WikiScholar registration complete:")
        self.assertIn("Class: Class 8", mail.outbox[-1].body)
        page = self.client.get("/").content.decode()
        self.assertIn("Student Registration", page)
        self.assertIn('<html lang="en">', page)

    def test_honeypot(self):
        vid = self.verify_email()
        r = self.post_json("/api/registration/submit/", self.payload(vid, website="http://spam"))
        self.assertEqual(r.status_code, 400)
        self.assertFalse(Student.objects.exists())


class OtpTests(WSTestCase):
    def test_typo_warning_then_confirm(self):
        self.client.get("/")
        r = self.post_json("/api/registration/email/send-otp/", {"email": "rahim@gmial.com"})
        self.assertEqual(r.json()["typo_suggestion"], "gmail.com")
        self.assertEqual(r.json()["message"], "Did you mean rahim@gmail.com?")
        r = self.post_json("/api/registration/email/send-otp/", {"email": "rahim@gmial.com", "confirm_typo": True})
        self.assertIn("verification_id", r.json())
        self.assertIsNone(suggest_email_domain("a@gmail.com"))
        self.assertIsNone(suggest_email_domain("a@du.ac.bd"))

    def test_typo_suggestions_for_missing_or_wrong_dot(self):
        for typed, want in [("a@gmailcom", "gmail.com"), ("a@gmail", "gmail.com"), ("a@gmail,com", "gmail.com"),
                            ("a@gamil.com", "gmail.com"), ("a@yahoocom", "yahoo.com"), ("a@hotmail.co", "hotmail.com"),
                            ("a@outlok.com", "outlook.com")]:
            self.assertEqual(suggest_email_domain(typed), want, typed)
        for fine in ["a@gmail.com", "a@wikimedia.org.bd", "a@mail.com", "a@du.ac.bd"]:
            self.assertIsNone(suggest_email_domain(fine), fine)

    def test_invalid_address_still_gets_a_suggestion(self):
        # "name@gmailcom" fails the format check, but the useful answer is the fix
        self.client.get("/")
        r = self.post_json("/api/registration/email/send-otp/", {"email": "rahim@gmailcom"})
        self.assertEqual(r.json()["suggested_email"], "rahim@gmail.com")
        self.assertFalse(EmailVerification.objects.exists())

    def test_instant_check_endpoint(self):
        r = self.client.get("/api/registration/email/check/", {"email": "Rahim@Gamil.com"})
        self.assertEqual(r.json()["suggested_email"], "rahim@gmail.com")
        self.assertEqual(self.client.get("/api/registration/email/check/", {"email": "r@gmail.com"}).json(), {})

    def test_wrong_code_locks_after_max_attempts(self):
        self.client.get("/")
        vid = self.post_json("/api/registration/email/send-otp/", {"email": "x@gmail.com"}).json()["verification_id"]
        code = re.search(r"\b(\d{6})\b", mail.outbox[-1].body).group(1)
        wrong = f"{(int(code) + 1) % 1_000_000:06d}"
        errors = [self.post_json("/api/registration/email/verify-otp/", {"verification_id": vid, "code": wrong}).json()["error"]
                  for _ in range(5)]
        self.assertEqual(errors[-1], "locked")
        r = self.post_json("/api/registration/email/verify-otp/", {"verification_id": vid, "code": code})
        self.assertEqual(r.json()["error"], "locked")

    def test_code_is_stored_hashed(self):
        self.client.get("/")
        vid = self.post_json("/api/registration/email/send-otp/", {"email": "x@gmail.com"}).json()["verification_id"]
        code = re.search(r"\b(\d{6})\b", mail.outbox[-1].body).group(1)
        self.assertNotIn(code, EmailVerification.objects.get(pk=vid).code_hash)

    @override_settings(WIKISCHOLAR={**__import__("django.conf").conf.settings.WIKISCHOLAR,
                                    "RATE_LIMITS": {**__import__("django.conf").conf.settings.WIKISCHOLAR["RATE_LIMITS"],
                                                    "otp_per_email": (2, 3600)}})
    def test_otp_rate_limited_per_email(self):
        self.client.get("/")
        codes = [self.post_json("/api/registration/email/send-otp/", {"email": "y@gmail.com"}).status_code for _ in range(3)]
        self.assertEqual(codes, [200, 200, 429])


class SchoolResolutionTests(WSTestCase):
    def test_new_school_created_pending_and_reused(self):
        s1 = self.register(school_id=None, school_name="Tongi Pilot  School")
        self.assertTrue(s1["school_pending"])
        pending = School.objects.get(name="Tongi Pilot School")
        self.assertEqual(pending.verification_status, "pending")
        self.register(email="b@gmail.com", school_id=None, school_name="tongi pilot school")
        self.assertEqual(Student.objects.filter(school=pending).count(), 2)

    def test_abbreviation_normalization_matches_existing(self):
        self.register(school_id=None, school_name="Tongi Govt. High School")
        student = Student.objects.get()
        self.assertEqual(student.school, self.school)
        self.assertEqual(student.school_name_as_entered, "Tongi Govt. High School")

    def test_school_id_from_other_upazila_is_ignored(self):
        other = School.objects.create(name="Sharsha School", district=self.jessore, upazila=self.sharsha)
        self.register(school_id=other.pk, school_name="Tongi Government High School")
        self.assertEqual(Student.objects.get().school, self.school)

    def test_typeahead_api_scoped_to_upazila(self):
        School.objects.create(name="Kaliakair Girls School", district=self.gazipur, upazila=self.kaliakair)
        r = self.client.get("/api/reference/schools/", {"upazila": self.tongi.pk, "q": "tongi high"})
        names = [s["name"] for s in r.json()["schools"]]
        self.assertEqual(names, ["Tongi Government High School"])
        r = self.client.get("/api/reference/schools/", {"upazila": self.tongi.pk, "q": "kaliakair"})
        self.assertEqual(r.json()["schools"], [])


class DatabaseIntegrityTests(WSTestCase):
    def test_students_cannot_be_hard_deleted(self):
        self.register()
        with self.assertRaises(Exception):
            with transaction.atomic(), connection.cursor() as c:
                c.execute("DELETE FROM students")
        self.assertEqual(Student.all_objects.count(), 1)

    def test_audit_log_is_append_only(self):
        self.register()
        with self.assertRaises(Exception):
            with transaction.atomic(), connection.cursor() as c:
                c.execute("UPDATE audit_logs SET action = 'tampered'")

    def test_upazila_district_composite_fk(self):
        self.register()
        with self.assertRaises(IntegrityError):
            with transaction.atomic(), connection.cursor() as c:
                # The FK is DEFERRABLE INITIALLY DEFERRED; force the check now.
                c.execute("SET CONSTRAINTS students_upazila_in_district IMMEDIATE")
                c.execute("UPDATE students SET upazila_id = %s", [self.sharsha.pk])

    def test_phone_check_constraint(self):
        self.register()
        with self.assertRaises(IntegrityError):
            with transaction.atomic(), connection.cursor() as c:
                c.execute("UPDATE students SET phone = '12345'")

    def test_class_and_relation_check_constraints(self):
        self.register()
        with self.assertRaises(IntegrityError):
            with transaction.atomic(), connection.cursor() as c:
                c.execute("UPDATE students SET current_class = '11'")
        with self.assertRaises(IntegrityError):
            with transaction.atomic(), connection.cursor() as c:
                c.execute("UPDATE students SET guardian_relation = 'other', guardian_relation_other = ''")

    def test_orm_delete_refused(self):
        self.register()
        with self.assertRaises(Exception):
            Student.objects.get().delete()
