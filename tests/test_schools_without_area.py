"""Schools whose thana isn't known (e.g. imported from a list with districts only) belong to
their whole district: suggested and duplicate-checked from every area, until an admin sets the area."""
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.core.models import AuditLog
from apps.reference import importer
from apps.reference import services as ref
from apps.reference.models import School
from apps.registration.models import Student

from .base import WSTestCase


class SchoolsWithoutAreaTests(WSTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.admin)

    def upload(self, text):
        f = SimpleUploadedFile("schools.csv", text.encode("utf-8"), content_type="text/csv")
        return self.client.post("/dashboard/schools/import/", {"file": f, "status": "verified"})

    def district_school(self, name="Gazipur Ideal School", **extra):
        return School.objects.create(name=name, district=self.gazipur, thana=None,
                                     verification_status="verified", source="import", **extra)

    # ---- import ----------------------------------------------------------------------------- #
    def test_import_with_blank_areas(self):
        r = self.upload("District,Thana,School name\n"
                        "Gazipur,,Gazipur Ideal School\n"
                        "Gazipur,Tongi,Tongi Pilot School\n"
                        "Jessore,  ,Jessore Zilla School\n")
        self.assertEqual(r.context["counts"]["new"], 3)
        self.assertContains(r, "Not known")
        self.client.post("/dashboard/schools/import/", {"op": "confirm"})
        ideal = School.objects.get(name="Gazipur Ideal School")
        self.assertEqual((ideal.district, ideal.thana, ideal.verification_status), (self.gazipur, None, "verified"))
        self.assertEqual(School.objects.get(name="Jessore Zilla School").district, self.jessore)
        self.assertEqual(School.objects.get(name="Tongi Pilot School").thana, self.tongi)

    def test_import_without_the_area_column(self):
        rows = importer.read_rows("District,School name\nGazipur,Gazipur Ideal School\n".encode())
        created, planned = importer.apply(rows, actor=self.admin)
        self.assertEqual(planned[0]["result"], "new")
        self.assertEqual((created[0].district, created[0].thana), (self.gazipur, None))

    def test_duplicate_checks_cover_the_whole_district(self):
        self.district_school()
        planned = importer.plan(importer.read_rows((
            "District,Thana,School name\n"
            "Gazipur,,Tongi Govt High School\n"         # listed in Tongi: a district-wide row matches it
            "Gazipur,Kaliakair,Gazipur Ideal School\n"  # listed without an area: matches from any area
            "Gazipur,,Kaliakair Model School\n"
            "Gazipur,Kaliakair,Kaliakair Model School\n"  # repeats the district-wide row above
            "Gazipur,Tonggi,X School\n"                 # a misspelt area is still an error
        ).encode()))
        self.assertEqual([r["result"] for r in planned], ["exists", "exists", "new", "repeated", "error"])
        self.assertIn("leave it blank", planned[4]["message"])

    def test_missing_district_column_is_refused(self):
        with self.assertRaises(importer.ImportFileError):
            importer.read_rows("Thana,School name\nTongi,X School\n".encode())

    # ---- public form ---------------------------------------------------------------------------- #
    def test_suggested_from_every_area_and_matched_when_typed(self):
        school = self.district_school()
        url = f"/api/reference/schools/?district={self.gazipur.pk}&thana={self.kaliakair.pk}&q=ideal"
        self.client.logout()
        found = {s["name"]: s for s in self.client.get(url).json()["schools"]}
        self.assertEqual((found["Gazipur Ideal School"]["area"], found["Gazipur Ideal School"]["same_area"]),
                         ("", False))
        page = self.client.get("/").content.decode()  # the form still renders
        self.assertIn("school_name", page)
        # picked from the suggestions
        s = self.register(thana=self.kaliakair.pk, school_id=school.pk, school_name=school.name)
        self.assertEqual(Student.objects.get(wikischolar_id=s["wikischolar_id"]).school, school)
        # typed by hand in another area: matched, not added again as a new pending school
        s = self.register(email="typed@gmail.com", phone="01812345678", thana=self.tongi.pk, school_id="",
                          school_name="gazipur ideal school")
        self.assertEqual(Student.objects.get(wikischolar_id=s["wikischolar_id"]).school, school)
        self.assertEqual(School.objects.filter(name__iexact="Gazipur Ideal School").count(), 1)

    # ---- dashboard ------------------------------------------------------------------------------ #
    def test_list_filter_detail_and_student_editor(self):
        school = self.district_school()
        r = self.client.get(f"/dashboard/schools/?district={self.gazipur.pk}&thana=none")
        self.assertEqual([s.name for s in r.context["page"]], ["Gazipur Ideal School"])
        self.assertContains(r, "Thana not known")
        r = self.client.get(f"/dashboard/schools/{school.pk}/")
        self.assertContains(r, "Thana not known, Gazipur")
        self.assertContains(r, "Set thana")
        # the student editor's school list for an area includes the district's schools without an area
        names = [s["name"] for s in self.client.get(f"/api/reference/schools/?thana={self.tongi.pk}&all=1")
                 .json()["schools"]]
        self.assertIn("Gazipur Ideal School", names)
        self.assertIn("Tongi Government High School", names)
        r = self.client.get(f"/api/reference/schools/?thana={self.sharsha.pk}&all=1")
        self.assertNotIn("Gazipur Ideal School", [s["name"] for s in r.json()["schools"]])  # other district

    def test_set_area_later(self):
        school = self.district_school()
        self.client.post(f"/dashboard/schools/{school.pk}/", {"op": "set_area", "thana": self.kaliakair.pk})
        school.refresh_from_db()
        self.assertEqual(school.thana, self.kaliakair)
        self.assertTrue(AuditLog.objects.filter(action="school.area_set", entity_id=str(school.pk)).exists())
        # an area of another district is refused
        self.client.post(f"/dashboard/schools/{school.pk}/", {"op": "set_area", "thana": self.sharsha.pk})
        school.refresh_from_db()
        self.assertEqual(school.thana, self.kaliakair)

    def test_set_area_refused_when_that_area_lists_the_name(self):
        school = self.district_school("Tongi Government High School")  # same name as the Tongi school
        r = self.client.post(f"/dashboard/schools/{school.pk}/", {"op": "set_area", "thana": self.tongi.pk},
                             follow=True)
        self.assertContains(r, "already listed in Tongi")
        school.refresh_from_db()
        self.assertIsNone(school.thana)

    def test_duplicate_review_and_merge_take_the_area(self):
        keep = self.district_school("Tongi Govt High School")
        pairs = ref.find_duplicate_pairs(district_id=self.gazipur.pk)
        self.assertIn({keep.pk, self.school.pk}, [{a.pk, b.pk} for a, b, _ in pairs])
        self.client.post("/dashboard/schools/merge/", {"keep": keep.pk, "duplicate": self.school.pk})
        keep.refresh_from_db()
        self.assertEqual(keep.thana, self.tongi)  # learnt from the merged duplicate
        self.assertEqual(School.all_objects.get(pk=self.school.pk).merged_into, keep)
        # schools in different districts are never merged
        other = School.objects.create(name="Tongi Govt High School", district=self.jessore, thana=None,
                                      verification_status="verified", source="import")
        with self.assertRaises(ValueError):
            ref.merge_schools(keep=keep, duplicate=other, request=self.fake_request())

    def test_messages_name_the_district_when_the_area_is_unknown(self):
        self.district_school()
        r = self.client.post("/dashboard/schools/add/", {"district": self.gazipur.pk, "thana": self.kaliakair.pk,
                                                          "name": "Gazipur Ideal School"})
        self.assertContains(r, "already listed in Gazipur (thana not known)")
        in_tongi = School.objects.create(name="Gazipur Ideal School", district=self.gazipur, thana=self.tongi,
                                         verification_status="verified")
        r = self.client.post(f"/dashboard/schools/{in_tongi.pk}/", {"op": "set_area", "thana": self.kaliakair.pk},
                             follow=True)
        self.assertContains(r, "already listed in Gazipur (thana not known)")
        r = self.client.get(f"/dashboard/schools/duplicates/?district={self.gazipur.pk}")
        self.assertContains(r, "Thana not known")
        self.assertNotContains(r, "<td>, Gazipur</td>", html=False)

    def test_remove_and_restore(self):
        school = self.district_school()
        self.client.post(f"/dashboard/schools/{school.pk}/", {"op": "remove", "reason": "test"})
        self.assertTrue(School.all_objects.get(pk=school.pk).is_deleted)
        self.client.post(f"/dashboard/schools/{school.pk}/", {"op": "restore"})
        self.assertFalse(School.all_objects.get(pk=school.pk).is_deleted)

    def fake_request(self):
        r = self.client.get("/dashboard/").wsgi_request
        r.user = self.admin
        return r
