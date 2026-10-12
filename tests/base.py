import json
import re

from django.core import mail
from django.core.cache import cache
from django.test import TestCase

from apps.core.models import Admin, Role
from apps.reference.models import District, Region, School, Thana


class WSTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.dhaka = Region.objects.create(code="dhaka", name="Dhaka", name_bn="ঢাকা", sort_order=1)
        cls.khulna = Region.objects.create(code="khulna", name="Khulna", name_bn="খুলনা", sort_order=2)
        cls.gazipur = District.objects.create(code="gazipur", name="Gazipur", name_bn="গাজীপুর", region=cls.dhaka)
        cls.jessore = District.objects.create(code="jessore", name="Jessore", name_bn="যশোর", region=cls.khulna)
        cls.tongi = Thana.objects.create(district=cls.gazipur, name="Tongi", name_bn="টঙ্গী")
        cls.kaliakair = Thana.objects.create(district=cls.gazipur, name="Kaliakair", name_bn="কালিয়াকৈর")
        cls.sharsha = Thana.objects.create(district=cls.jessore, name="Sharsha", name_bn="শার্শা")
        cls.school = School.objects.create(name="Tongi Government High School", district=cls.gazipur,
                                           thana=cls.tongi, verification_status="verified", source="admin")
        cls.super = Admin.objects.create_user(email="super@ws.test", password="x-Strong-pass-123",
                                              full_name="Super", role=Role.SUPER_ADMIN)
        cls.admin = Admin.objects.create_user(email="admin@ws.test", password="x-Strong-pass-123",
                                              full_name="Admin", role=Role.ADMIN)
        cls.viewer = Admin.objects.create_user(email="viewer@ws.test", password="x-Strong-pass-123",
                                               full_name="Viewer", role=Role.VIEWER)

    def setUp(self):
        cache.clear()  # rate-limit counters

    # ---- helpers ------------------------------------------------------------ #
    def post_json(self, url, data, client=None):
        return (client or self.client).post(url, json.dumps(data), content_type="application/json")

    def verify_email(self, email="rahim@gmail.com", client=None):
        client = client or self.client
        client.get("/")
        mail.outbox.clear()
        r = self.post_json("/api/registration/email/send-otp/", {"email": email}, client)
        self.assertEqual(r.status_code, 200, r.content)
        vid = r.json()["verification_id"]
        code = re.search(r"\b(\d{6})\b", mail.outbox[-1].body).group(1)
        r = self.post_json("/api/registration/email/verify-otp/", {"verification_id": vid, "code": code}, client)
        self.assertEqual(r.json(), {"verified": True})
        return vid

    def payload(self, vid, **over):
        data = {
            "student_name": "Rahim Uddin", "gender": "male",
            "guardian_name": "Karim Uddin", "guardian_relation": "father",
            "district": self.gazipur.pk, "thana": self.tongi.pk,
            "school_id": self.school.pk, "school_name": self.school.name,
            "current_class": "8", "class_roll": "12", "student_id_sid": "", "section": "", "heard_from": "school",
            "phone": "01712345678", "email": "rahim@gmail.com", "updates_opt_in": True,
            "verification_id": vid, "policy_consent": True, "guardian_declaration": True, "website": "",
        }
        data.update(over)
        return data

    def register(self, email="rahim@gmail.com", **over):
        vid = self.verify_email(email)
        r = self.post_json("/api/registration/submit/", self.payload(vid, email=email, **over))
        self.assertEqual(r.status_code, 201, r.content)
        return r.json()["summary"]
