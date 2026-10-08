"""School suggestions cover the whole district (a student may attend a school in another upazila / area);
schools in the student's own area come first, and each suggestion shows its area."""
from apps.reference.models import School
from apps.registration.models import Student

from .base import WSTestCase


class DistrictSuggestionTests(WSTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        # The same common name in two areas of Gazipur, and one in another district
        cls.ghs_tongi = School.objects.create(name="Government Girls High School", district=cls.gazipur,
                                              upazila=cls.tongi, verification_status="verified")
        cls.ghs_kaliakair = School.objects.create(name="Government Girls High School", district=cls.gazipur,
                                                  upazila=cls.kaliakair, verification_status="verified")
        cls.kaliakair_pilot = School.objects.create(name="Kaliakair Pilot High School", district=cls.gazipur,
                                                    upazila=cls.kaliakair, verification_status="verified")
        cls.pending = School.objects.create(name="Kaliakair New Academy", district=cls.gazipur,
                                            upazila=cls.kaliakair, verification_status="pending")
        cls.jessore_school = School.objects.create(name="Sharsha Pilot High School", district=cls.jessore,
                                                   upazila=cls.sharsha, verification_status="verified")

    def suggest(self, q, upazila=None, district=None):
        district = district or self.gazipur
        url = f"/api/reference/schools/?district={district.pk}&q={q}" + (f"&upazila={upazila.pk}" if upazila else "")
        return self.client.get(url).json()["schools"]

    def test_suggestions_start_from_the_third_letter(self):
        self.assertEqual(self.suggest("t"), [])
        self.assertEqual(self.suggest("to"), [])
        self.assertEqual(self.suggest("%20to%20"), [])
        self.assertIn("Tongi Government High School", [s["name"] for s in self.suggest("ton")])
        self.client.force_login(self.admin)  # the student editor's full list sends no query at all
        names = [s["name"] for s in self.client.get(f"/api/reference/schools/?upazila={self.kaliakair.pk}&all=1")
                 .json()["schools"]]
        self.assertIn("Kaliakair New Academy", names)

    def test_whole_district_with_own_area_first(self):
        rows = self.suggest("pilot high school", upazila=self.tongi)
        names = [r["name"] for r in rows]
        self.assertIn("Kaliakair Pilot High School", names)       # another area of the district
        self.assertNotIn("Sharsha Pilot High School", names)       # another district
        rows = self.suggest("government girls", upazila=self.kaliakair)
        self.assertEqual([(r["area"], r["same_area"]) for r in rows[:2]], [("Kaliakair", True), ("Tongi", False)])
        self.assertEqual(rows[0]["area_bn"], "কালিয়াকৈর")

    def test_public_suggestions_stay_approved_only(self):
        names = [r["name"] for r in self.suggest("kaliakair", upazila=self.kaliakair)]
        self.assertNotIn("Kaliakair New Academy", names)

    def test_needs_district_or_upazila(self):
        r = self.client.get("/api/reference/schools/?q=x")
        self.assertEqual((r.status_code, r.json()["error"]), (400, "district_or_upazila_required"))

    def test_picking_a_school_in_another_area_keeps_the_students_area(self):
        s = self.register(upazila=self.tongi.pk, school_id=self.kaliakair_pilot.pk,
                          school_name="Kaliakair Pilot High School")
        st = Student.objects.get(wikischolar_id=s["wikischolar_id"])
        self.assertEqual((st.upazila, st.school, st.school_resolution), (self.tongi, self.kaliakair_pilot, "selected"))

    def test_a_school_from_another_district_is_not_accepted_by_id(self):
        s = self.register(upazila=self.tongi.pk, school_id=self.jessore_school.pk, school_name="Sharsha Pilot High School")
        st = Student.objects.get(wikischolar_id=s["wikischolar_id"])
        self.assertNotEqual(st.school, self.jessore_school)
        self.assertEqual((st.school.upazila, st.school_resolution), (self.tongi, "created"))

    def test_a_typed_name_is_only_matched_in_the_chosen_area(self):
        # Not picked from the list: a common name elsewhere in the district must not be assumed
        s = self.register(upazila=self.tongi.pk, school_id=None, school_name="Kaliakair Pilot High School")
        st = Student.objects.get(wikischolar_id=s["wikischolar_id"])
        self.assertNotEqual(st.school, self.kaliakair_pilot)
        self.assertEqual(st.school.verification_status, "pending")

    def test_dashboard_editor_keeps_a_school_from_another_area(self):
        s = self.register(upazila=self.tongi.pk, school_id=self.kaliakair_pilot.pk,
                          school_name="Kaliakair Pilot High School")
        wsid = s["wikischolar_id"]
        st = Student.objects.get(wikischolar_id=wsid)
        self.client.force_login(self.admin)
        page = self.client.get(f"/dashboard/students/{wsid}/edit/").content.decode()
        self.assertIn("Kaliakair Pilot High School (Kaliakair)", page)
        data = {"student_name": st.student_name, "gender": st.gender, "guardian_name": "New Guardian",
                "guardian_relation": st.guardian_relation, "guardian_relation_other": "",
                "district": st.district_id, "upazila": st.upazila_id, "school": st.school_id,
                "current_class": st.current_class, "class_roll": st.class_roll, "student_id_sid": "",
                "section": "", "phone": st.phone, "email": st.email, "updates_opt_in": "on", "reason": ""}
        r = self.client.post(f"/dashboard/students/{wsid}/edit/", data)
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Student.objects.get(wikischolar_id=wsid).school, self.kaliakair_pilot)
        r = self.client.post(f"/dashboard/students/{wsid}/edit/", {**data, "school": self.jessore_school.pk})
        self.assertEqual(r.context["form"].errors["school"], ["This school is not in the selected district."])
