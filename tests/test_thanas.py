"""Thana: the government's thana list with cantonments and "Other thana" next to the thanas, grouped
headings for any custom group, and checks on the seed file built from the BANBEIS list."""
import importlib.util
import io
import json
from pathlib import Path

from django.conf import settings
from django.core.management import call_command

from apps.reference.models import District, Region, Thana
from apps.registration.models import Student

from .base import WSTestCase

GCC = "Gazipur City Corporation"  # a custom group: still shown as a heading


class AreaTestCase(WSTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.tongi_east = Thana.objects.create(district=cls.gazipur, name="Tongi East", name_bn="টঙ্গী পূর্ব",
                                                group=GCC, group_bn="গাজীপুর সিটি কর্পোরেশন")
        cls.cantonment = Thana.objects.create(district=cls.gazipur, name="Gazipur Cantonment", name_bn="গাজীপুর সেনানিবাস",
                                                group=Thana.CANTONMENT, group_bn="সেনানিবাস")
        cls.other = Thana.objects.create(district=cls.gazipur, name="Other thana (not listed)",
                                           name_bn="অন্য থানা (তালিকায় নেই)", group=Thana.OTHER, group_bn="অন্যান্য")


class PublicFormTests(AreaTestCase):
    def test_api_lists_areas_grouped_in_order(self):
        r = self.client.get(f"/api/reference/districts/{self.gazipur.pk}/thanas/")
        rows = r.json()["thanas"]
        self.assertEqual([(u["name"], u["group"]) for u in rows], [
            ("Tongi East", GCC), ("Gazipur Cantonment", "Cantonments"),
            ("Kaliakair", "Thanas"), ("Tongi", "Thanas"), ("Other thana (not listed)", "Not in the list")])
        self.assertEqual(rows[0]["group_bn"], "গাজীপুর সিটি কর্পোরেশন")
        self.assertEqual(rows[2]["group_bn"], "থানা")

    def test_form_label_and_hint(self):
        page = self.client.get("/").content.decode()
        self.assertIn("Thana", page)
        self.assertIn("থানা", page)
        self.assertIn("Not listed? Choose “Other thana (not listed)” at the end.", page)

    def test_register_with_a_thana(self):
        s = self.register(thana=self.tongi_east.pk, school_id=None, school_name="Tongi East Model School")
        self.assertEqual(s["thana"], f"Tongi East ({GCC})")
        st = Student.objects.get(wikischolar_id=s["wikischolar_id"])
        self.assertEqual(st.thana, self.tongi_east)
        self.assertEqual(st.school.thana, self.tongi_east)  # new school filed under the thana

    def test_area_from_another_district_is_refused(self):
        vid = self.verify_email()
        r = self.post_json("/api/registration/submit/", self.payload(vid, district=self.jessore.pk,
                                                                     thana=self.tongi_east.pk))
        self.assertEqual(r.json()["errors"]["thana"], ["Choose a thana in the selected district."])

    def test_display_name(self):
        self.assertEqual(self.tongi_east.display_name, f"Tongi East ({GCC})")
        self.assertEqual(self.cantonment.display_name, "Gazipur Cantonment")
        self.assertEqual(self.tongi.display_name, "Tongi")


class DashboardTests(AreaTestCase):
    def test_other_area_students_are_flagged_and_filterable(self):
        self.register(thana=self.other.pk, school_id=None, school_name="Some School")
        self.register(email="b@gmail.com")
        self.client.force_login(self.viewer)
        self.assertContains(self.client.get("/dashboard/"), "1 student chose “Other thana (not listed)”")
        r = self.client.get("/dashboard/students/?area_kind=other")
        self.assertEqual(r.context["count"], 1)
        r = self.client.get("/dashboard/students/?area_kind=thana")
        self.assertEqual(r.context["count"], 1)

    def test_area_dropdowns_are_grouped(self):
        s = self.register(thana=self.tongi_east.pk, school_id=None, school_name="Tongi East Model School")
        self.client.force_login(self.admin)
        page = self.client.get(f"/dashboard/students/{s['wikischolar_id']}/edit/").content.decode()
        self.assertIn(f'<optgroup label="{GCC}">', page)
        self.assertIn('<optgroup label="Not in the list">', page)
        self.assertLess(page.index(GCC), page.index('label="Thanas"'))
        detail = self.client.get(f"/dashboard/students/{s['wikischolar_id']}/").content.decode()
        self.assertIn("Thana", detail)

    def test_add_area_with_a_group_on_district_page(self):
        self.client.force_login(self.admin)
        r = self.client.get(f"/dashboard/locations/districts/{self.gazipur.pk}/")
        self.assertContains(r, "Thanas")
        self.client.post(f"/dashboard/locations/districts/{self.gazipur.pk}/",
                         {"op": "add_thana", "name": "Pubail", "name_bn": "পুবাইল", "group": GCC})
        new = Thana.objects.get(district=self.gazipur, name="Pubail")
        self.assertEqual((new.group, new.group_bn), (GCC, "গাজীপুর সিটি কর্পোরেশন"))
        self.client.post(f"/dashboard/locations/districts/{self.gazipur.pk}/",
                         {"op": "add_thana", "name": "Sreepur", "group": "Made-up group"})
        self.assertEqual(Thana.objects.get(district=self.gazipur, name="Sreepur").group, "")

    def test_school_import_accepts_area_column_and_thanas(self):
        from apps.reference import importer
        rows = importer.read_rows("District,Area,School name\nGazipur,Tongi East,Tongi East Model School\n".encode())
        planned = importer.plan(rows)
        self.assertEqual(planned[0]["thana_id"], self.tongi_east.pk)


class SeedCommandTests(WSTestCase):
    def test_seed_loads_thanas_with_groups_and_is_idempotent(self):
        data = {"regions": [{"code": "dhaka", "name": "Dhaka"}], "districts": [{
            "code": "gazipur", "name": "Gazipur", "region": "dhaka",
            "thanas": [{"name": "Tongi"},
                       {"name": "Rajendrapur Cantonment", "name_bn": "রাজেন্দ্রপুর সেনানিবাস", "group": "Cantonment",
                        "group_bn": "সেনানিবাস"},
                       {"name": "Kaliakair", "group": "Other"}]}]}  # an existing row only gets its group added
        path = Path(settings.BASE_DIR) / "tests" / "_seed_tmp.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        try:
            call_command("seed_reference", file=str(path), stdout=io.StringIO())
            call_command("seed_reference", file=str(path), stdout=io.StringIO())
        finally:
            path.unlink()
        self.assertEqual(Thana.objects.filter(district=self.gazipur, name="Rajendrapur Cantonment").count(), 1)
        self.assertEqual(Thana.objects.get(district=self.gazipur, name="Rajendrapur Cantonment").group, "Cantonment")
        self.assertEqual(Thana.objects.get(district=self.gazipur, name="Kaliakair").group, "Other")
        self.assertEqual(Thana.objects.get(district=self.gazipur, name="Tongi").group, "")

    def test_seed_keeps_dashboard_renames_and_if_empty_skips(self):
        # Every deploy restarts the web container, which runs seed_reference: it must not undo dashboard renames.
        self.client.force_login(self.super)
        self.client.post("/dashboard/locations/", {"op": "rename_region", "region": self.dhaka.pk,
                                                   "name": "Jamuna", "name_bn": "যমুনা"})
        self.dhaka.refresh_from_db()
        self.assertEqual((self.dhaka.name, self.dhaka.name_bn), ("Jamuna", "যমুনা"))
        District.objects.filter(pk=self.gazipur.pk).update(name="Gazipur Zila")
        data = {"regions": [{"code": "dhaka", "name": "Dhaka", "name_bn": "ঢাকা"},
                            {"code": "sylhet", "name": "Sylhet"}],
                "districts": [{"code": "gazipur", "name": "Gazipur", "region": "dhaka"},
                              {"code": "sylhet", "name": "Sylhet", "region": "sylhet"}]}
        path = Path(settings.BASE_DIR) / "tests" / "_seed_tmp.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        try:
            call_command("seed_reference", file=str(path), if_empty=True, stdout=io.StringIO())
            self.assertFalse(Region.objects.filter(code="sylhet").exists())  # regions exist: nothing done
            call_command("seed_reference", file=str(path), stdout=io.StringIO())
        finally:
            path.unlink()
        self.dhaka.refresh_from_db()
        self.assertEqual((self.dhaka.name, self.dhaka.name_bn), ("Jamuna", "যমুনা"))
        self.assertEqual(District.objects.get(pk=self.gazipur.pk).name, "Gazipur Zila")
        self.assertTrue(Region.objects.filter(code="sylhet", name="Sylhet").exists())  # missing rows still added
        self.assertTrue(District.objects.filter(code="sylhet").exists())


class SeedCoverageTests(WSTestCase):
    """data/reference_seed.json: the BANBEIS e-survey 2024 districts and thanas, the upazilas created
    since, the cantonments and one "Other thana" per district (see PROJECT_GUIDE, Thana)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.seed = json.loads((Path(settings.BASE_DIR) / "data" / "reference_seed.json").read_text(encoding="utf-8"))
        cls.thanas = [(d["code"], t) for d in cls.seed["districts"] for t in d["thanas"]]

    def of_group(self, group):
        return [t for _, t in self.thanas if t.get("group", "") == group]

    def test_64_districts_with_government_spelling(self):
        names = {d["name"] for d in self.seed["districts"]}
        self.assertEqual(len(names), 64)
        for name in ("Barishal", "Bogura", "Chattogram", "Cumilla", "Jashore", "Khagrachhari", "Maulvibazar",
                     "Netrakona", "Norail", "Brahmanbaria", "Cox's Bazar", "Chapainawabganj"):
            self.assertIn(name, names)
        self.assertFalse(names & {"Chittagong", "Comilla", "Jessore", "Coxs Bazar", "Brahamanbaria", "Nawabganj"})

    def test_thana_counts(self):
        # 560 from the 2024 sheet + 11 upazilas created since; cantonments and "Other" on top
        self.assertEqual(len(self.of_group("")), 571)
        self.assertGreaterEqual(len(self.of_group(Thana.CANTONMENT)), 30)
        for d in self.seed["districts"]:
            self.assertEqual(len([t for t in d["thanas"] if t.get("group") == Thana.OTHER]), 1, d["code"])

    def test_names_are_unique_within_a_district_and_bilingual(self):
        for d in self.seed["districts"]:
            names = [t["name"].casefold() for t in d["thanas"]]
            self.assertEqual(len(names), len(set(names)), d["code"])
            for t in d["thanas"]:
                self.assertTrue(t.get("name_bn"), (d["code"], t["name"]))
                self.assertEqual(t["name"], " ".join(t["name"].split()))
                self.assertFalse(t["name"].endswith("Upazila"), t["name"])

    def test_seed_command_loads_the_real_file(self):
        # The fixtures' districts share codes with the seed ("gazipur", "jessore"), so the seed loads on top;
        # "Tongi" and "Sharsha" are fixture rows ("Sharsha" is in the seed too).
        call_command("seed_reference", stdout=io.StringIO())
        self.assertEqual(Thana.objects.filter(group=Thana.OTHER).count(), 64)
        self.assertEqual(Thana.objects.filter(group=Thana.CANTONMENT).count(), len(self.of_group(Thana.CANTONMENT)))
        self.assertTrue(Thana.objects.filter(district=self.gazipur, name="Gazipur Sadar", name_bn__gt="").exists())


def _seed_builder():
    spec = importlib.util.spec_from_file_location(
        "build_thana_seed", Path(settings.BASE_DIR) / "scripts" / "build_thana_seed.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SeedBuilderTests(WSTestCase):
    def test_sheet_thana_names_are_cleaned(self):
        clean = _seed_builder().clean_thana
        self.assertEqual(clean("Kaptai  Upazila"), "Kaptai")
        self.assertEqual(clean("Belai Chhari  Upazi"), "Belai Chhari")
        self.assertEqual(clean("Jurai Chhari Upazil"), "Jurai Chhari")
        self.assertEqual(clean("Rangamati Sadar  Up"), "Rangamati Sadar")
        self.assertEqual(clean("Uttara  Paschim"), "Uttara Paschim")
        self.assertEqual(clean("Nesarabad (Swarupkati)"), "Nesarabad (Swarupkati)")


class BeforeTheRenameTests(AreaTestCase):
    """Links, files and saved wording from before "Upazila / Area" became "Thana" keep working."""

    def test_old_upazila_links_filter_by_thana(self):
        self.register(thana=self.other.pk, school_id=None, school_name="Some School")
        self.register(email="b@gmail.com")
        self.client.force_login(self.viewer)
        r = self.client.get(f"/dashboard/students/?district={self.gazipur.pk}&upazila={self.other.pk}")
        self.assertEqual(r.context["count"], 1)
        r = self.client.get("/dashboard/students/?area_kind=upazila")
        self.assertEqual(r.context["count"], 1)
        r = self.client.get(f"/dashboard/schools/?district={self.gazipur.pk}&upazila={self.tongi.pk}")
        self.assertContains(r, "Tongi Government High School")

    def test_import_accepts_the_old_headings(self):
        from apps.reference import importer
        for heading in ("Upazila", "Upazila / Area", "Area", "Thana"):
            rows = importer.read_rows(f"District,{heading},School name\nGazipur,Tongi,Tongi Model School\n".encode())
            self.assertEqual(importer.plan(rows)[0]["thana_id"], self.tongi.pk, heading)

    def test_saved_wording_with_upazila_placeholder_still_fills_in(self):
        from apps.notifications import services as notify
        from apps.registration import emails
        values = emails.confirmation_values(emails._SAMPLE_SUMMARY)
        self.assertEqual(notify.fill("Thana: {thana}; old: {upazila}", values), "Thana: Tongi; old: Tongi")
