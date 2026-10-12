"""Government school data (BANBEIS list): `import_banbeis_schools`, EIIN, the school page's
government data, and school names in capitals."""
import io
import tempfile
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

from django.core.management import call_command
from django.db import IntegrityError, transaction

from apps.core.models import AuditLog
from apps.reference import banbeis
from apps.reference.models import School, SchoolAlias
from apps.registration.models import Student

from .base import WSTestCase

HEADER = ["DIVISION_NAME", "DISTRICT_NAME", "THANA_NAME", "INSTITUTE_TYPE_NAME", "EDUCATION_LEVEL_NAME", "EIIN_NO",
          "INSTITUTE_NAME", "POST_OFFICE_NAME", "EMAIL", "MANAGEMENT_NAME", "IS_MPO", "INSTITUTE_FOR_WHOM",
          "GEOGRAPHICAL_POSITION_NAME", "AREA_STATUS_NAME"]


def row(eiin, name, thana="Kaliakair", district="Gazipur", management="NON-GOVERNMENT", **over):
    r = dict(zip(HEADER, ["Dhaka", district, thana, "SCHOOL", "Secondary", eiin, name, "Kaliakair", "x@gmail.com",
                          management, "YES", "CO-EDUCATION-SEPERATE SHIFT", "HAOR/BILL (OUTSIDE EMBANKMENT)", "RURAL"]))
    r.update(over)
    return [r[h] for h in HEADER]


def write_xlsx(rows, path):
    """A minimal .xlsx (inline strings) with a title row above the headings, like the BANBEIS export."""
    def cells(values, r):
        return "".join(f'<c r="{chr(65 + i)}{r}" t="inlineStr"><is><t>{escape(v)}</t></is></c>'
                       for i, v in enumerate(values))
    data = [["School Data based on Esurvey: 2024"], HEADER, *rows]
    sheet = ('<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="http://schemas.openxmlformats.org/'
             'spreadsheetml/2006/main"><sheetData>'
             + "".join(f'<row r="{i}">{cells(v, i)}</row>' for i, v in enumerate(data, start=1))
             + "</sheetData></worksheet>")
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("xl/worksheets/sheet1.xml", sheet)
    return path


class ImportTests(WSTestCase):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()
        super().tearDown()

    def run_import(self, rows, *args):
        path = write_xlsx(rows, Path(self.tmp.name) / "schools.xlsx")
        out = io.StringIO()
        call_command("import_banbeis_schools", str(path), *args, stdout=out)
        return out.getvalue()

    def test_creates_schools_with_government_data_and_a_rerun_changes_nothing(self):
        out = self.run_import([row("100014", "shakhria  high school", management="CRISTIAN MISSIONARY")])
        self.assertIn("1 created, 0 matched by name, 0 updated, 0 unchanged, 0 skipped.", out)
        s = School.objects.get(eiin="100014")
        self.assertEqual((s.name, s.thana, s.district, s.verification_status, s.source),
                         ("SHAKHRIA HIGH SCHOOL", self.kaliakair, self.gazipur, "verified", "government"))
        self.assertEqual((s.management, s.mpo, s.education_level, s.institute_for, s.geographical_position,
                          s.area_status, s.institute_type, s.division, s.post_office, s.email),
                         ("christian_missionary", "yes", "secondary", "co_education_separate_shift", "haor_outside",
                          "rural", "school", "Dhaka", "Kaliakair", "x@gmail.com"))
        self.assertEqual(AuditLog.objects.get(action="school.government_import").meta["created"], 1)
        out = self.run_import([row("100014", "SHAKHRIA HIGH SCHOOL", management="CRISTIAN MISSIONARY")])
        self.assertIn("0 created, 0 matched by name, 0 updated, 1 unchanged", out)
        self.assertEqual(AuditLog.objects.filter(action="school.government_import").count(), 1)

    def test_dry_run_saves_nothing(self):
        out = self.run_import([row("100014", "SHAKHRIA HIGH SCHOOL")], "--dry-run")
        self.assertIn("(dry run)", out)
        self.assertFalse(School.objects.filter(eiin="100014").exists())

    def test_matches_an_existing_school_by_name_and_keeps_its_students(self):
        pilot = School.objects.create(name="Kaliakair Pilot High School", district=self.gazipur, thana=self.kaliakair)
        s = self.register(thana=self.kaliakair.pk, school_id=pilot.pk, school_name=pilot.name)
        out = self.run_import([row("100099", "KALIAKAIR PILOT HIGH SCHOOL")])
        self.assertIn("0 created, 1 matched by name", out)
        pilot.refresh_from_db()
        self.assertEqual((pilot.eiin, pilot.verification_status), ("100099", "verified"))
        self.assertEqual(Student.objects.get(wikischolar_id=s["wikischolar_id"]).school_id, pilot.pk)

    def test_updates_by_eiin_and_keeps_the_old_name_as_an_alias(self):
        self.run_import([row("100014", "SHAKHRIA HIGH SCHOOL")])
        out = self.run_import([row("100014", "SHAKHARIA SECONDARY SCHOOL", management="GOVERNMENT")])
        self.assertIn("0 created, 0 matched by name, 1 updated", out)
        s = School.objects.get(eiin="100014")
        self.assertEqual((s.name, s.management), ("SHAKHARIA SECONDARY SCHOOL", "government"))
        self.assertTrue(SchoolAlias.objects.filter(school=s, alias_text="SHAKHRIA HIGH SCHOOL").exists())

    def test_rows_that_dont_resolve_are_skipped_and_reported(self):
        out = self.run_import([row("100014", "SHAKHRIA HIGH SCHOOL"),
                               row("100015", "NOWHERE SCHOOL", thana="Nowhere"),
                               row("100016", "JESSORE SCHOOL", district="Atlantis"),
                               row("12AB", "BAD EIIN SCHOOL")])
        self.assertIn("1 created, 0 matched by name, 0 updated, 0 unchanged, 3 skipped.", out)
        self.assertIn("Row 4: skipped (EIIN 100015, NOWHERE SCHOOL, Gazipur / Nowhere)", out)

    def test_value_cleanup(self):
        values = row("1", "X", INSTITUTE_FOR_WHOM="None", POST_OFFICE_NAME="None", AREA_STATUS_NAME="SOMEWHERE")
        data, unknown = banbeis.government_data(dict(zip(HEADER, values)))
        self.assertEqual((data["institute_for"], data["post_office"], data["area_status"]), ("", "", ""))
        self.assertEqual(unknown, ["AREA_STATUS_NAME=SOMEWHERE"])


class EiinTests(WSTestCase):
    def test_eiin_is_unique_and_six_digits_in_the_database(self):
        School.objects.create(name="A School", district=self.gazipur, thana=self.tongi, eiin="123456")
        with self.assertRaises(IntegrityError), transaction.atomic():
            School.objects.create(name="B School", district=self.gazipur, thana=self.tongi, eiin="123456")
        with self.assertRaises(IntegrityError), transaction.atomic():
            School.objects.create(name="C School", district=self.gazipur, thana=self.tongi, eiin="12a456")
        School.objects.create(name="D School", district=self.gazipur, thana=self.tongi)  # blank EIINs don't clash
        School.objects.create(name="E School", district=self.gazipur, thana=self.tongi)

    def test_typeahead_finds_a_school_by_eiin(self):
        School.objects.filter(pk=self.school.pk).update(eiin="100014")
        r = self.client.get(f"/api/reference/schools/?district={self.gazipur.pk}&q=100014")
        self.assertEqual([(s["name"], s["eiin"]) for s in r.json()["schools"]], [("TONGI GOVERNMENT HIGH SCHOOL", "100014")])
        self.client.force_login(self.viewer)
        self.assertContains(self.client.get("/dashboard/schools/?q=100014"), "TONGI GOVERNMENT HIGH SCHOOL")

    def test_edit_government_data_on_the_school_page(self):
        School.objects.create(name="Other School", district=self.gazipur, thana=self.tongi, eiin="222222")
        self.client.force_login(self.admin)
        url = f"/dashboard/schools/{self.school.pk}/"
        r = self.client.post(url, {"op": "details", "eiin": "12345"})
        self.assertContains(r, "An EIIN is 6 digits.")
        r = self.client.post(url, {"op": "details", "eiin": "222222"})
        self.assertContains(r, "EIIN 222222 already belongs to OTHER SCHOOL.")
        r = self.client.post(url, {"op": "details", "eiin": "111111", "management": "government", "mpo": "no",
                                   "division": "Dhaka", "email": "tghs@example.com"})
        self.assertRedirects(r, url)
        self.school.refresh_from_db()
        self.assertEqual((self.school.eiin, self.school.management, self.school.mpo), ("111111", "government", "no"))
        log = AuditLog.objects.get(action="school.details_updated")
        self.assertEqual((log.before["eiin"], log.after["eiin"]), ("", "111111"))
        self.assertContains(self.client.get(url), "Government data")

    def test_viewer_cannot_edit_government_data(self):
        self.client.force_login(self.viewer)
        self.client.post(f"/dashboard/schools/{self.school.pk}/", {"op": "details", "eiin": "111111"})
        self.school.refresh_from_db()
        self.assertEqual(self.school.eiin, "")


class CapitalsMigrationTests(WSTestCase):
    def test_existing_names_and_aliases_are_converted(self):
        from importlib import import_module

        from django.apps import apps
        School.objects.filter(pk=self.school.pk).update(name="Tongi Government High School")
        alias = SchoolAlias.objects.create(school=self.school, alias_text="x")
        SchoolAlias.objects.filter(pk=alias.pk).update(alias_text="Tongi Govt High")
        import_module("apps.reference.migrations.0010_uppercase_school_names").forwards(apps, None)
        self.assertEqual(School.objects.get(pk=self.school.pk).name, "TONGI GOVERNMENT HIGH SCHOOL")
        self.assertEqual(SchoolAlias.objects.get(pk=alias.pk).alias_text, "TONGI GOVT HIGH")
