"""Upazila / Area: city-corporation thanas, cantonments and "Other area" next to the upazilas, and a check
that the seed file leaves no area of Bangladesh out."""
import io
import json
from pathlib import Path

from django.conf import settings
from django.core.management import call_command

from apps.reference.models import Upazila
from apps.registration.models import Student

from .base import WSTestCase

GCC = "Gazipur City Corporation"


class AreaTestCase(WSTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.tongi_east = Upazila.objects.create(district=cls.gazipur, name="Tongi East", name_bn="টঙ্গী পূর্ব",
                                                group=GCC, group_bn="গাজীপুর সিটি কর্পোরেশন")
        cls.cantonment = Upazila.objects.create(district=cls.gazipur, name="Gazipur Cantonment", name_bn="গাজীপুর সেনানিবাস",
                                                group=Upazila.CANTONMENT, group_bn="সেনানিবাস")
        cls.other = Upazila.objects.create(district=cls.gazipur, name="Other area (not listed)",
                                           name_bn="অন্য এলাকা (তালিকায় নেই)", group=Upazila.OTHER, group_bn="অন্যান্য")


class PublicFormTests(AreaTestCase):
    def test_api_lists_areas_grouped_in_order(self):
        r = self.client.get(f"/api/reference/districts/{self.gazipur.pk}/upazilas/")
        rows = r.json()["upazilas"]
        self.assertEqual([(u["name"], u["group"]) for u in rows], [
            ("Tongi East", GCC), ("Gazipur Cantonment", "Cantonments"),
            ("Kaliakair", "Upazilas"), ("Tongi", "Upazilas"), ("Other area (not listed)", "Not in the list")])
        self.assertEqual(rows[0]["group_bn"], "গাজীপুর সিটি কর্পোরেশন")
        self.assertEqual(rows[2]["group_bn"], "উপজেলা")

    def test_form_label_and_hint(self):
        page = self.client.get("/").content.decode()
        self.assertIn("Upazila / Area", page)
        self.assertIn("উপজেলা / এলাকা", page)
        self.assertIn("choose your thana under its city corporation", page)

    def test_register_with_a_thana(self):
        s = self.register(upazila=self.tongi_east.pk, school_id=None, school_name="Tongi East Model School")
        self.assertEqual(s["upazila"], f"Tongi East ({GCC})")
        st = Student.objects.get(wikischolar_id=s["wikischolar_id"])
        self.assertEqual(st.upazila, self.tongi_east)
        self.assertEqual(st.school.upazila, self.tongi_east)  # new school filed under the thana

    def test_area_from_another_district_is_refused(self):
        vid = self.verify_email()
        r = self.post_json("/api/registration/submit/", self.payload(vid, district=self.jessore.pk,
                                                                     upazila=self.tongi_east.pk))
        self.assertEqual(r.json()["errors"]["upazila"], ["Choose an upazila or area in the selected district."])

    def test_display_name(self):
        self.assertEqual(self.tongi_east.display_name, f"Tongi East ({GCC})")
        self.assertEqual(self.cantonment.display_name, "Gazipur Cantonment")
        self.assertEqual(self.tongi.display_name, "Tongi")


class DashboardTests(AreaTestCase):
    def test_other_area_students_are_flagged_and_filterable(self):
        self.register(upazila=self.other.pk, school_id=None, school_name="Some School")
        self.register(email="b@gmail.com")
        self.client.force_login(self.viewer)
        self.assertContains(self.client.get("/dashboard/"), "1 student chose “Other area (not listed)”")
        r = self.client.get("/dashboard/students/?area_kind=other")
        self.assertEqual(r.context["count"], 1)
        r = self.client.get("/dashboard/students/?area_kind=upazila")
        self.assertEqual(r.context["count"], 1)

    def test_area_dropdowns_are_grouped(self):
        s = self.register(upazila=self.tongi_east.pk, school_id=None, school_name="Tongi East Model School")
        self.client.force_login(self.admin)
        page = self.client.get(f"/dashboard/students/{s['wikischolar_id']}/edit/").content.decode()
        self.assertIn(f'<optgroup label="{GCC}">', page)
        self.assertIn('<optgroup label="Not in the list">', page)
        self.assertLess(page.index(GCC), page.index('label="Upazilas"'))
        detail = self.client.get(f"/dashboard/students/{s['wikischolar_id']}/").content.decode()
        self.assertIn("Upazila / Area", detail)

    def test_add_area_with_a_group_on_district_page(self):
        self.client.force_login(self.admin)
        r = self.client.get(f"/dashboard/locations/districts/{self.gazipur.pk}/")
        self.assertContains(r, "Upazilas &amp; areas")
        self.client.post(f"/dashboard/locations/districts/{self.gazipur.pk}/",
                         {"op": "add_upazila", "name": "Pubail", "name_bn": "পুবাইল", "group": GCC})
        new = Upazila.objects.get(district=self.gazipur, name="Pubail")
        self.assertEqual((new.group, new.group_bn), (GCC, "গাজীপুর সিটি কর্পোরেশন"))
        self.client.post(f"/dashboard/locations/districts/{self.gazipur.pk}/",
                         {"op": "add_upazila", "name": "Sreepur", "group": "Made-up group"})
        self.assertEqual(Upazila.objects.get(district=self.gazipur, name="Sreepur").group, "")

    def test_school_import_accepts_area_column_and_thanas(self):
        from apps.reference import importer
        rows = importer.read_rows("District,Area,School name\nGazipur,Tongi East,Tongi East Model School\n".encode())
        planned = importer.plan(rows)
        self.assertEqual(planned[0]["upazila_id"], self.tongi_east.pk)


class SeedCommandTests(WSTestCase):
    def test_seed_loads_areas_with_groups_and_is_idempotent(self):
        data = {"regions": [{"code": "dhaka", "name": "Dhaka"}], "districts": [{
            "code": "gazipur", "name": "Gazipur", "region": "dhaka",
            "upazilas": [{"name": "Tongi"}],
            "areas": [{"name": "Tongi East", "name_bn": "টঙ্গী পূর্ব", "group": GCC, "group_bn": "গাজীপুর সিটি কর্পোরেশন"},
                      {"name": "Kaliakair", "group": "Other"}]}]}  # an existing row only gets its group added
        path = Path(settings.BASE_DIR) / "tests" / "_seed_tmp.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        try:
            call_command("seed_reference", file=str(path), stdout=io.StringIO())
            call_command("seed_reference", file=str(path), stdout=io.StringIO())
        finally:
            path.unlink()
        self.assertEqual(Upazila.objects.filter(district=self.gazipur, name="Tongi East").count(), 1)
        self.assertEqual(Upazila.objects.get(district=self.gazipur, name="Tongi East").group, GCC)
        self.assertEqual(Upazila.objects.get(district=self.gazipur, name="Kaliakair").group, "Other")


class SeedCoverageTests(WSTestCase):
    """data/reference_seed.json must cover every area of Bangladesh (see PROJECT_GUIDE, Upazila / Area)."""
    CITY_CORPORATIONS = {
        "Dhaka North City Corporation", "Dhaka South City Corporation", "Chattogram City Corporation",
        "Khulna City Corporation", "Rajshahi City Corporation", "Sylhet City Corporation",
        "Barishal City Corporation", "Rangpur City Corporation", "Mymensingh City Corporation",
        "Gazipur City Corporation", "Narayanganj City Corporation", "Cumilla City Corporation",
        "Bogura City Corporation"}  # the 13th, gazetted 14 May 2026

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.seed = json.loads((Path(settings.BASE_DIR) / "data" / "reference_seed.json").read_text(encoding="utf-8"))

    def areas(self, group=None):
        return [(d["code"], a) for d in self.seed["districts"] for a in d.get("areas", [])
                if group is None or a["group"] == group]

    def test_all_64_districts_and_503_upazilas(self):
        # 495 until May 2026; 5 gazetted 4 Jun 2026 and 3 notified 8 Jul 2026 make 503
        self.assertEqual(len(self.seed["districts"]), 64)
        self.assertEqual(sum(len(d["upazilas"]) for d in self.seed["districts"]), 503)

    def test_all_13_city_corporations_have_areas(self):
        groups = {a["group"] for _, a in self.areas()} - {Upazila.CANTONMENT, Upazila.OTHER}
        self.assertEqual(groups, self.CITY_CORPORATIONS)

    def test_cantonments_are_listed(self):
        self.assertGreaterEqual(len(self.areas(Upazila.CANTONMENT)), 30)

    def test_every_district_has_one_other_area(self):
        for d in self.seed["districts"]:
            other = [a for a in d.get("areas", []) if a["group"] == Upazila.OTHER]
            self.assertEqual(len(other), 1, d["code"])

    def test_names_are_unique_within_a_district_and_bilingual(self):
        for d in self.seed["districts"]:
            names = [u["name"].casefold() for u in d["upazilas"] + d.get("areas", [])]
            self.assertEqual(len(names), len(set(names)), d["code"])
            for a in d.get("areas", []):
                self.assertTrue(a.get("name_bn") and a.get("group_bn"), (d["code"], a["name"]))

    def test_seed_command_loads_the_real_file(self):
        # The fixtures' districts share codes with the seed ("gazipur", "jessore"), so the seed loads on top;
        # "Tongi" is a fixture-only upazila.
        call_command("seed_reference", stdout=io.StringIO())
        self.assertEqual(Upazila.objects.filter(group="").exclude(name="Tongi").count(), 503)
        self.assertEqual(Upazila.objects.filter(group=Upazila.OTHER).count(), 64)
        self.assertEqual(Upazila.objects.exclude(group="").count(), len(self.areas()))
