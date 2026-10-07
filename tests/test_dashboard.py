import io
import os
import tempfile
from datetime import timedelta

from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.utils import timezone

from apps.core.models import AuditLog
from apps.notifications.models import NotificationLog
from apps.reference.models import District, Region, School, SchoolAlias
from apps.registration.models import EditHistory, Student

from .base import WSTestCase


class PermissionTests(WSTestCase):
    def test_anonymous_redirected_to_login(self):
        r = self.client.get("/dashboard/students/")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/dashboard/login/", r["Location"])

    def test_viewer_can_read_but_not_change(self):
        s = self.register()
        self.client.force_login(self.viewer)
        for url in ["/dashboard/", "/dashboard/students/", f"/dashboard/students/{s['wikischolar_id']}/",
                    "/dashboard/schools/", "/dashboard/locations/", "/dashboard/messages/"]:
            self.assertEqual(self.client.get(url).status_code, 200, url)
        for url in ["/dashboard/students/export.csv", f"/dashboard/students/{s['wikischolar_id']}/edit/",
                    "/dashboard/messages/compose/", "/dashboard/audit/", "/dashboard/admins/"]:
            self.assertEqual(self.client.get(url).status_code, 403, url)

    def test_admin_cannot_manage_admins(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get("/dashboard/admins/").status_code, 403)
        self.assertEqual(self.client.get("/dashboard/audit/").status_code, 200)

    def test_every_page_renders_for_super_admin(self):
        s = self.register()
        self.client.force_login(self.super)
        wsid = s["wikischolar_id"]
        for url in ["/dashboard/", "/dashboard/students/", f"/dashboard/students/?district={self.gazipur.pk}",
                    f"/dashboard/students/{wsid}/", f"/dashboard/students/{wsid}/edit/", "/dashboard/students/archived/",
                    "/dashboard/messages/", "/dashboard/messages/compose/", "/dashboard/schools/",
                    f"/dashboard/schools/?district={self.gazipur.pk}&upazila={self.tongi.pk}",
                    f"/dashboard/schools/{self.school.pk}/", "/dashboard/schools/duplicates/",
                    "/dashboard/schools/add/", f"/dashboard/schools/add/?district={self.gazipur.pk}",
                    "/dashboard/schools/?status=removed",
                    "/dashboard/locations/", f"/dashboard/locations/districts/{self.gazipur.pk}/",
                    "/dashboard/audit/", "/dashboard/admins/"]:
            self.assertEqual(self.client.get(url).status_code, 200, url)


class StudentAdminTests(WSTestCase):
    def setUp(self):
        super().setUp()
        self.s = self.register()
        self.wsid = self.s["wikischolar_id"]
        self.client.force_login(self.admin)

    def edit_data(self, **over):
        st = Student.objects.get(wikischolar_id=self.wsid)
        data = {"student_name": st.student_name, "gender": st.gender,
                "guardian_name": st.guardian_name, "guardian_relation": st.guardian_relation,
                "guardian_relation_other": st.guardian_relation_other,
                "district": st.district_id, "upazila": st.upazila_id, "school": st.school_id,
                "current_class": st.current_class, "class_roll": st.class_roll, "student_id_sid": st.student_id_sid,
                "section": st.section, "phone": st.phone, "email": st.email, "updates_opt_in": "on", "reason": "Parent called"}
        data.update(over)
        return data

    def test_edit_writes_history_and_audit(self):
        r = self.client.post(f"/dashboard/students/{self.wsid}/edit/", self.edit_data(phone="01898765432"))
        self.assertEqual(r.status_code, 302)
        h = EditHistory.objects.get(field_name="phone")
        self.assertEqual((h.old_value, h.new_value, h.reason), ("01712345678", "01898765432", "Parent called"))
        self.assertTrue(AuditLog.objects.filter(action="student.updated").exists())

    def test_edit_relation_to_other_requires_text(self):
        r = self.client.post(f"/dashboard/students/{self.wsid}/edit/", self.edit_data(guardian_relation="other"))
        self.assertEqual(r.status_code, 200)
        self.assertIn("guardian_relation_other", r.context["form"].errors)
        r = self.client.post(f"/dashboard/students/{self.wsid}/edit/",
                             self.edit_data(guardian_relation="other", guardian_relation_other="Uncle"))
        self.assertEqual(r.status_code, 302)
        st = Student.objects.get(wikischolar_id=self.wsid)
        self.assertEqual((st.guardian_relation, st.guardian_relation_label), ("other", "Uncle"))
        self.assertContains(self.client.get(f"/dashboard/students/{self.wsid}/"), "(Uncle)")

    def test_viewing_a_record_is_audited(self):
        self.client.get(f"/dashboard/students/{self.wsid}/")
        self.assertTrue(AuditLog.objects.filter(action="student.viewed", actor=self.admin).exists())

    def test_export_is_audited(self):
        r = self.client.get("/dashboard/students/export.csv")
        self.assertEqual(r.status_code, 200)
        self.assertIn(self.wsid, b"".join(r.streaming_content).decode() if r.streaming else r.content.decode())
        self.assertTrue(AuditLog.objects.filter(action="students.exported").exists())

    def test_archive_and_restore(self):
        self.client.post(f"/dashboard/students/{self.wsid}/archive/", {"reason": "duplicate entry"})
        self.assertFalse(Student.objects.filter(wikischolar_id=self.wsid).exists())
        st = Student.all_objects.get(wikischolar_id=self.wsid)
        self.assertTrue(st.is_deleted)
        self.assertEqual(st.deleted_by, self.admin)
        self.client.post(f"/dashboard/students/{self.wsid}/restore/")
        self.assertTrue(Student.objects.filter(wikischolar_id=self.wsid).exists())

    def test_filters(self):
        self.register(email="k@gmail.com", district=self.jessore.pk, upazila=self.sharsha.pk,
                      school_id=None, school_name="Sharsha Pilot School", gender="female")
        r = self.client.get("/dashboard/students/", {"region": self.khulna.pk})
        self.assertEqual(r.context["count"], 1)
        r = self.client.get("/dashboard/students/", {"district": [self.gazipur.pk, self.jessore.pk]})
        self.assertEqual(r.context["count"], 2)
        r = self.client.get("/dashboard/students/", {"gender": "female", "class": "8"})
        self.assertEqual(r.context["count"], 1)

    def test_filter_toggle_counts_only_narrowing_filters(self):
        r = self.client.get("/dashboard/students/")
        self.assertContains(r, 'id="filtersToggle"')
        self.assertEqual(r.context["active_filters"], 0)
        r = self.client.get("/dashboard/students/", {"gender": "female", "class": ["7", "8"], "q": "a",
                                                     "sort": "name", "batch_size": "10"})
        self.assertEqual(r.context["active_filters"], 3)


    def test_admin_edit_is_english_only(self):
        r = self.client.post(f"/dashboard/students/{self.wsid}/edit/", self.edit_data(student_name="রহিম"))
        self.assertEqual(r.status_code, 200)
        self.assertIn("student_name", r.context["form"].errors)

    def test_edit_section_and_numeric_roll(self):
        r = self.client.get(f"/dashboard/students/{self.wsid}/edit/")
        self.assertNotContains(r, "Date of birth")
        r = self.client.post(f"/dashboard/students/{self.wsid}/edit/", self.edit_data(section="B", class_roll="7"))
        self.assertEqual(r.status_code, 302)
        st = Student.objects.get(wikischolar_id=self.wsid)
        self.assertEqual((st.section, st.class_roll), ("B", "7"))
        r = self.client.post(f"/dashboard/students/{self.wsid}/edit/", self.edit_data(class_roll="7A"))
        self.assertEqual(r.status_code, 200)
        self.assertIn("class_roll", r.context["form"].errors)

    def test_registered_between_filter_reads_british_and_iso_dates(self):
        today = timezone.localdate()
        for params, count in [({"from": today.strftime("%d/%m/%Y")}, 1), ({"to": today.isoformat()}, 1),
                              ({"from": (today + timedelta(days=1)).strftime("%d/%m/%Y")}, 0)]:
            r = self.client.get("/dashboard/students/", params)
            self.assertEqual(r.context["count"], count, params)
        r = self.client.get("/dashboard/students/", {"to": today.isoformat()})
        self.assertContains(r, f'value="{today:%d/%m/%Y}"')

    def test_school_names_from_dashboard_are_english_only(self):
        self.client.post("/dashboard/schools/add/", {"district": self.gazipur.pk, "upazila": self.tongi.pk,
                                                      "name": "টঙ্গী স্কুল"})
        self.assertFalse(School.objects.filter(name="টঙ্গী স্কুল").exists())
        self.client.post(f"/dashboard/schools/{self.school.pk}/", {"op": "rename", "name": "টঙ্গী"})
        self.school.refresh_from_db()
        self.assertEqual(self.school.name, "Tongi Government High School")


class RegionAssignmentTests(WSTestCase):
    def test_reassigning_district_changes_student_region_and_is_audited(self):
        s = self.register()
        self.client.force_login(self.admin)
        r = self.client.post("/dashboard/locations/", {"op": "assign", f"region_{self.gazipur.pk}": self.khulna.pk})
        self.assertEqual(r.status_code, 302)
        st = Student.objects.get(wikischolar_id=s["wikischolar_id"])
        self.assertEqual(st.region, self.khulna)
        log = AuditLog.objects.get(action="reference.district_region_changed")
        self.assertEqual(log.entity_id, str(self.gazipur.pk))
        # public API reflects it immediately
        d = next(x for x in self.client.get("/api/reference/districts/").json()["districts"] if x["id"] == self.gazipur.pk)
        self.assertEqual(d["region"]["name"], "Khulna")

    def test_unassigned_district_and_region_lifecycle(self):
        self.client.force_login(self.admin)
        self.client.post("/dashboard/locations/", {"op": "add_region", "name": "Mymensingh", "name_bn": "ময়মনসিংহ",
                                                    "code": "mymensingh", "sort_order": 7})
        new = Region.objects.get(code="mymensingh")
        self.client.post("/dashboard/locations/", {"op": "assign", f"region_{self.jessore.pk}": ""})
        self.assertIsNone(District.objects.get(pk=self.jessore.pk).region)
        self.assertEqual(self.client.get("/dashboard/locations/").context["unassigned"][0].pk, self.jessore.pk)
        self.client.post("/dashboard/locations/", {"op": "archive_region", "region": new.pk})
        self.assertFalse(Region.objects.filter(pk=new.pk).exists())
        self.assertTrue(Region.all_objects.filter(pk=new.pk, is_deleted=True).exists())

    def test_cannot_archive_region_in_use(self):
        self.client.force_login(self.admin)
        self.client.post("/dashboard/locations/", {"op": "archive_region", "region": self.dhaka.pk})
        self.assertTrue(Region.objects.filter(pk=self.dhaka.pk).exists())

    def test_viewer_cannot_reassign(self):
        self.client.force_login(self.viewer)
        self.client.post("/dashboard/locations/", {"op": "assign", f"region_{self.gazipur.pk}": self.khulna.pk})
        self.assertEqual(District.objects.get(pk=self.gazipur.pk).region, self.dhaka)


class SchoolMergeTests(WSTestCase):
    def test_merge_moves_students_and_creates_alias(self):
        self.register(school_id=None, school_name="Tongi Govt High Skool")
        dup = School.objects.get(verification_status="pending")
        st = Student.objects.get()
        self.assertEqual(st.school, dup)
        self.client.force_login(self.admin)
        r = self.client.get("/dashboard/schools/duplicates/")
        self.assertEqual(r.status_code, 200)
        self.client.post("/dashboard/schools/merge/", {"keep": self.school.pk, "duplicate": dup.pk})
        st.refresh_from_db(); dup.refresh_from_db()
        self.assertEqual(st.school, self.school)
        self.assertEqual(st.school_name_as_entered, "Tongi Govt High Skool")  # dual storage preserved
        self.assertEqual((dup.verification_status, dup.merged_into), ("merged", self.school))
        self.assertTrue(SchoolAlias.objects.filter(school=self.school, alias_text="Tongi Govt High Skool").exists())
        self.assertTrue(EditHistory.objects.filter(student=st, field_name="school").exists())
        # the next registrant typing the misspelling lands on the canonical school
        self.register(email="n@gmail.com", school_id=None, school_name="tongi govt high skool")
        self.assertEqual(Student.objects.get(email="n@gmail.com").school, self.school)


class SchoolAddRemoveTests(WSTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.admin)

    def add(self, name, upazila=None, district=None, **extra):
        return self.client.post("/dashboard/schools/add/", {
            "district": (district or self.gazipur).pk, "upazila": (upazila or self.tongi).pk, "name": name, **extra})

    def test_add_new_school(self):
        r = self.add("Tongi  Pilot Girls School")
        school = School.objects.get(name="Tongi Pilot Girls School")
        self.assertRedirects(r, f"/dashboard/schools/{school.pk}/")
        self.assertEqual((school.verification_status, school.source, school.verified_by), ("verified", "admin", self.admin))
        self.assertTrue(AuditLog.objects.filter(action="school.created", entity_id=str(school.pk)).exists())

    def test_same_name_or_alias_is_refused(self):
        SchoolAlias.objects.create(school=self.school, alias_text="Tongi Boys School")
        for name in ["tongi government high school", "TONGI BOYS SCHOOL"]:
            r = self.add(name)
            self.assertContains(r, "This school is already listed.")
            self.assertContains(r, f'href="/dashboard/schools/{self.school.pk}/"')
        self.assertEqual(School.objects.count(), 1)
        # the same name in another upazila is a different school
        self.add("Tongi Government High School", upazila=self.kaliakair)
        self.assertEqual(School.objects.count(), 2)

    def test_similar_name_needs_confirmation(self):
        r = self.add("Tongi Goverment High Scool")
        self.assertContains(r, "have a similar name")
        self.assertFalse(School.objects.filter(name="Tongi Goverment High Scool").exists())
        self.add("Tongi Goverment High Scool", confirm="1")
        self.assertTrue(School.objects.filter(name="Tongi Goverment High Scool").exists())
        # "Govt" is the same name once abbreviations are expanded, so it is refused outright
        self.assertContains(self.add("Tongi Govt. High School", confirm="1"), "This school is already listed.")

    def test_upazila_must_be_in_district(self):
        r = self.add("Sharsha Model School", upazila=self.sharsha, district=self.gazipur)
        self.assertContains(r, "Choose the district and upazila.")
        self.assertFalse(School.objects.filter(name="Sharsha Model School").exists())

    def test_viewer_cannot_add_or_remove(self):
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get("/dashboard/schools/add/").status_code, 403)
        self.client.post(f"/dashboard/schools/{self.school.pk}/", {"op": "remove", "reason": "x"})
        self.assertTrue(School.objects.filter(pk=self.school.pk).exists())

    def test_remove_blocked_while_students_are_linked(self):
        self.register()
        r = self.client.post(f"/dashboard/schools/{self.school.pk}/", {"op": "remove", "reason": "x"}, follow=True)
        self.assertContains(r, "1 student is linked to this school")
        self.assertTrue(School.objects.filter(pk=self.school.pk).exists())

    def test_remove_and_restore(self):
        SchoolAlias.objects.create(school=self.school, alias_text="TGHS")
        r = self.client.post(f"/dashboard/schools/{self.school.pk}/", {"op": "remove", "reason": "added by mistake"})
        self.assertEqual(r.status_code, 302)
        self.assertFalse(School.objects.filter(pk=self.school.pk).exists())
        self.assertTrue(AuditLog.objects.filter(action="school.removed", entity_id=str(self.school.pk)).exists())
        self.assertContains(self.client.get("/dashboard/schools/?status=removed"), self.school.name)
        self.assertNotContains(self.client.get("/dashboard/schools/"), self.school.name)
        # registrants no longer land on it, even through its alias
        self.register(school_id=self.school.pk, school_name="TGHS")
        self.assertNotEqual(Student.objects.get().school_id, self.school.pk)
        # restoring is fine: the pending "TGHS" school isn't the same name
        self.client.post(f"/dashboard/schools/{self.school.pk}/", {"op": "restore"})
        self.assertTrue(School.objects.filter(pk=self.school.pk).exists())

    def test_restore_refused_when_same_name_was_added_since(self):
        self.client.post(f"/dashboard/schools/{self.school.pk}/", {"op": "remove", "reason": "x"})
        self.add("Tongi Government High School")
        r = self.client.post(f"/dashboard/schools/{self.school.pk}/", {"op": "restore"}, follow=True)
        self.assertContains(r, "is already listed in Tongi")
        self.assertFalse(School.objects.filter(pk=self.school.pk).exists())

    def test_typeahead_shows_pending_schools_to_staff_only(self):
        School.objects.create(name="Tongi Pending School", district=self.gazipur, upazila=self.tongi)
        url = f"/api/reference/schools/?upazila={self.tongi.pk}&q=tongi&pending=1"
        names = [s["name"] for s in self.client.get(url).json()["schools"]]
        self.assertIn("Tongi Pending School", names)
        self.client.logout()
        names = [s["name"] for s in self.client.get(url).json()["schools"]]
        self.assertNotIn("Tongi Pending School", names)


class SchoolImportTests(WSTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.admin)

    def upload(self, text, status="verified", name="schools.csv"):
        f = SimpleUploadedFile(name, text.encode("utf-8"), content_type="text/csv")
        return self.client.post("/dashboard/schools/import/", {"file": f, "status": status})

    def test_template_is_just_the_headings_and_imports_once_filled_in(self):
        r = self.client.get("/dashboard/schools/import/template.csv")
        self.assertEqual(r["Content-Type"], "text/csv; charset=utf-8")
        self.assertIn("schools-import-template.csv", r["Content-Disposition"])
        self.assertTrue(r.content.startswith(b"\xef\xbb\xbf"))  # BOM for Excel
        self.assertEqual(r.content.decode("utf-8-sig").splitlines(), ["District,Upazila / Area,School name"])
        r = self.upload(r.content.decode("utf-8") + "Gazipur,Tongi,Tongi Pilot School\n")
        self.assertEqual(r.context["counts"]["new"], 1)

    def test_district_and_upazila_list(self):
        r = self.client.get("/dashboard/schools/import/locations.csv")
        self.assertEqual(r.content.decode("utf-8-sig").splitlines(), [
            "District,Upazila / Area,Group,District (Bangla),Upazila / Area (Bangla)",
            "Gazipur,Kaliakair,Upazilas,গাজীপুর,কালিয়াকৈর", "Gazipur,Tongi,Upazilas,গাজীপুর,টঙ্গী",
            "Jessore,Sharsha,Upazilas,যশোর,শার্শা"])
        r = self.client.get(f"/dashboard/schools/import/locations.csv?district={self.jessore.pk}")
        self.assertEqual(r.content.decode("utf-8-sig").splitlines()[1:], ["Jessore,Sharsha,Upazilas,যশোর,শার্শা"])
        self.assertIn("districts-and-upazilas-jessore.csv", r["Content-Disposition"])

    def test_preview_then_confirm(self):
        csv_text = ("District,Upazila,Name,Notes\n"
                    "gazipur, tongi ,Tongi Pilot School,x\n"
                    "Gazipur,Tongi,TONGI GOVT HIGH SCHOOL,\n"        # same as the listed school
                    "Gazipur,Tongi,Tongi Goverment High Scool,\n"    # similar
                    "Gazipur,Tongi,Tongi pilot school,\n"            # repeat of row 2
                    "Gazipur,Nowhere,Some School,\n"
                    "Narnia,Tongi,Some School,\n"
                    "Jessore,Sharsha,শার্শা স্কুল,\n"
                    "Gazipur,Kaliakair,,\n"                          # blank name: ignored
                    "যশোর,শার্শা,Sharsha Model School,\n")           # Bangla place names are fine
        r = self.upload(csv_text)
        self.assertEqual(r.context["counts"], {"new": 2, "similar": 1, "exists": 1, "repeated": 1, "error": 3})
        self.assertContains(r, "No upazila or area “Nowhere” in Gazipur.")
        self.assertContains(r, "Unknown district “Narnia”.")
        self.assertContains(r, "Same school as row 2.")
        self.assertEqual(School.objects.count(), 1)  # nothing saved yet
        similar_line = next(row["line"] for row in r.context["planned"] if row["result"] == "similar")
        r = self.client.post("/dashboard/schools/import/", {"op": "confirm", "add_similar": [similar_line]})
        self.assertRedirects(r, "/dashboard/schools/")
        names = set(School.objects.values_list("name", flat=True))
        self.assertEqual(names, {"Tongi Government High School", "Tongi Pilot School",
                                 "Tongi Goverment High Scool", "Sharsha Model School"})
        new = School.objects.get(name="Sharsha Model School")
        self.assertEqual((new.verification_status, new.source, new.upazila), ("verified", "import", self.sharsha))
        self.assertEqual(AuditLog.objects.get(action="school.imported").meta["created"], 3)
        # the upload is used once
        r = self.client.post("/dashboard/schools/import/", {"op": "confirm"}, follow=True)
        self.assertContains(r, "That upload has expired.")

    def test_similar_rows_are_skipped_unless_ticked_and_status_is_kept(self):
        self.upload("district,upazila,name\nGazipur,Tongi,Tongi Goverment High Scool\nGazipur,Tongi,Tongi Pilot School\n",
                    status="pending")
        self.client.post("/dashboard/schools/import/", {"op": "confirm"})
        self.assertEqual(School.objects.get(name="Tongi Pilot School").verification_status, "pending")
        self.assertFalse(School.objects.filter(name="Tongi Goverment High Scool").exists())

    def test_rechecked_on_confirm(self):
        self.upload("district,upazila,name\nGazipur,Tongi,Tongi Pilot School\n")
        self.client.post("/dashboard/schools/add/", {"district": self.gazipur.pk, "upazila": self.tongi.pk,
                                                     "name": "Tongi Pilot School"})
        self.client.post("/dashboard/schools/import/", {"op": "confirm"})
        self.assertEqual(School.objects.filter(name="Tongi Pilot School").count(), 1)

    def test_bad_files(self):
        self.assertContains(self.upload("school,place\nA,B\n"), "The first row must be the column headings")
        self.assertContains(self.upload("district,upazila,name\nGazipur,Tongi,\n"), "No school names found")
        r = self.client.post("/dashboard/schools/import/", {"status": "verified"})
        self.assertContains(r, "Choose a CSV file to upload.")

    def test_viewer_cannot_import(self):
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get("/dashboard/schools/import/").status_code, 403)
        self.assertEqual(self.client.get("/dashboard/schools/import/template.csv").status_code, 403)
        self.assertEqual(self.client.get("/dashboard/schools/import/locations.csv").status_code, 403)

    def test_management_command_uses_the_same_checks(self):
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8") as fh:
            fh.write("district,upazila,name\nGazipur,Tongi,Tongi Govt High School\nGazipur,Tongi,Tongi Pilot School\n"
                     "Gazipur,Nowhere,X School\n")
        out, err = io.StringIO(), io.StringIO()
        call_command("import_schools", fh.name, stdout=out, stderr=err)
        os.unlink(fh.name)
        self.assertIn("1 created, 1 already existed, 0 repeated, 1 with errors.", out.getvalue())
        self.assertIn("Row 4: No upazila or area “Nowhere” in Gazipur.", err.getvalue())
        self.assertEqual(School.objects.get(name="Tongi Pilot School").source, "import")


class MessagingTests(WSTestCase):
    def test_bulk_email_batch_opted_in_only_and_resend(self):
        self.register()
        self.register(email="nooptin@gmail.com", updates_opt_in=False)
        self.client.force_login(self.admin)
        mail.outbox.clear()
        r = self.client.get("/dashboard/messages/compose/")
        self.assertEqual(r.status_code, 200)
        r = self.client.post("/dashboard/messages/compose/", {"name": "Test batch",
            "channel": "email", "subject": "Hello {name}", "body": "Your ID is {wikischolar_id}",
            "opted_in_only": "on", "confirm_count": 1})
        self.assertEqual(r.status_code, 302, r.context and "form" in r.context and r.context["form"].errors)
        logs = NotificationLog.objects.filter(kind="bulk")
        self.assertEqual(logs.count(), 1)
        log = logs.get()
        self.assertEqual(log.email_batch.batch_code[:3], "EB-")
        self.assertEqual(log.status, "sent")
        self.assertIn(log.wikischolar_id, mail.outbox[-1].body)
        # delivery webhook marks it failed, then resend queues a linked retry
        from django.conf import settings
        token = settings.NOTIFICATIONS["WEBHOOK_TOKEN"]
        if token:
            log.provider_message_id = log.provider_message_id or "m-1"
            log.save(update_fields=["provider_message_id"])
            self.post_json(f"/notifications/webhook/email/?token={token}",
                           {"message_id": log.provider_message_id, "status": "bounced", "error": "mailbox full"})
        else:
            NotificationLog.objects.filter(pk=log.pk).update(status="bounced")
        code = log.email_batch.batch_code
        self.client.post(f"/dashboard/messages/{code}/resend/")
        retry = NotificationLog.objects.get(resend_of=log)
        self.assertEqual(retry.destination, log.destination)
        self.assertEqual(self.client.get(f"/dashboard/messages/{code}/").status_code, 200)

    def test_stale_confirm_count_blocks_send(self):
        self.register()
        self.client.force_login(self.admin)
        r = self.client.post("/dashboard/messages/compose/", {"name": "Test batch",
            "channel": "sms", "body": "Hi", "confirm_count": 99})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(NotificationLog.objects.filter(kind="bulk").exists())


class AdminManagementTests(WSTestCase):
    def test_super_admin_creates_and_deactivates(self):
        self.client.force_login(self.super)
        r = self.client.post("/dashboard/admins/", {"full_name": "New", "email": "New@ws.test", "role": "viewer",
                                                    "password": "Another-strong-pass-9"})
        self.assertEqual(r.status_code, 302)
        from apps.core.models import Admin
        new = Admin.objects.get(email="new@ws.test")
        self.client.post(f"/dashboard/admins/{new.pk}/", {"op": "role", "role": "admin"})
        new.refresh_from_db(); self.assertEqual(new.role, "admin")
        self.client.post(f"/dashboard/admins/{new.pk}/", {"op": "deactivate"})
        new.refresh_from_db(); self.assertFalse(new.is_active)
        self.assertTrue(AuditLog.objects.filter(action="admin.deactivate", entity_id=str(new.pk)).exists())
        c = self.client_class()
        r = c.post("/dashboard/login/", {"username": "new@ws.test", "password": "Another-strong-pass-9"})
        self.assertEqual(r.status_code, 200)  # stays on login page

    def test_cannot_demote_self(self):
        self.client.force_login(self.super)
        self.client.post(f"/dashboard/admins/{self.super.pk}/", {"op": "role", "role": "viewer"})
        self.super.refresh_from_db()
        self.assertEqual(self.super.role, "super_admin")

    def test_login_is_audited(self):
        self.client.post("/dashboard/login/", {"username": "admin@ws.test", "password": "x-Strong-pass-123"})
        self.assertTrue(AuditLog.objects.filter(action="admin.login", actor=self.admin).exists())


class BatchSplitTests(WSTestCase):
    def setUp(self):
        super().setUp()
        self.ids = [self.register(email=f"s{i}@gmail.com", updates_opt_in=i != 4)["wikischolar_id"]
                    for i in range(5)]
        self.client.force_login(self.admin)

    def test_split_into_batches_oldest_first(self):
        r = self.client.get("/dashboard/students/", {"batch_size": 2})
        self.assertEqual(r.context["count"], 5)
        self.assertEqual([(b["number"], b["first"], b["last"], b["count"]) for b in r.context["batches"]],
                         [(1, 1, 2, 2), (2, 3, 4, 2), (3, 5, 5, 1)])
        r = self.client.get("/dashboard/students/", {"batch_size": 2, "batch": 2})
        self.assertEqual(r.context["count"], 2)
        self.assertEqual([s.wikischolar_id for s in r.context["page"]], self.ids[2:4])
        self.assertEqual(len(r.context["batches"]), 3)  # the strip still lists every batch

    def test_batches_respect_other_filters_and_bad_input(self):
        r = self.client.get("/dashboard/students/", {"batch_size": 3, "batch": 2, "opt_in": "1"})
        self.assertEqual(r.context["count"], 1)  # 4 opted in -> a batch of 3, then 1
        r = self.client.get("/dashboard/students/", {"batch_size": "abc", "batch": 2})
        self.assertEqual(r.context["count"], 5)
        self.assertNotIn("batches", r.context)

    def test_export_and_message_one_batch(self):
        r = self.client.get("/dashboard/students/export.csv", {"batch_size": 2, "batch": 3})
        self.assertIn("batch-3", r["Content-Disposition"])
        body = b"".join(r.streaming_content).decode()
        self.assertIn(self.ids[4], body)
        self.assertNotIn(self.ids[0], body)
        r = self.client.post("/dashboard/messages/compose/", {"name": "Test batch",
            "batch_size": 2, "batch": 1, "sort": "oldest", "channel": "email", "subject": "Hi",
            "body": "Hello {name}", "opted_in_only": "on", "confirm_count": 2})
        self.assertEqual(r.status_code, 302)
        logs = NotificationLog.objects.filter(kind="bulk")
        self.assertEqual(sorted(logs.values_list("wikischolar_id", flat=True)), self.ids[:2])
        self.assertEqual(logs.first().email_batch.filter_snapshot["batch"], "1")


class EmailSettingsTests(WSTestCase):
    def form(self, **over):
        data = {"op": "save", "provider": "brevo", "username": "8a1b2c@smtp-brevo.com",
                "password": "xsmtpsib-secret", "from_email": "noreply@wikimedia.org.bd", "from_name": "WikiScholar",
                "host": "", "port": 587, "security": "starttls", "is_active": "on"}
        data.update(over)
        return data

    def test_only_super_admin(self):
        for user, code in [(self.viewer, 403), (self.admin, 403), (self.super, 200)]:
            self.client.force_login(user)
            self.assertEqual(self.client.get("/dashboard/settings/email/").status_code, code)

    def test_save_encrypts_password_and_audits_without_it(self):
        from apps.notifications.models import EmailSettings
        self.client.force_login(self.super)
        r = self.client.post("/dashboard/settings/email/", self.form())
        self.assertEqual(r.status_code, 302)
        cfg = EmailSettings.active()
        self.assertNotIn("xsmtpsib-secret", cfg.password_encrypted)
        self.assertEqual(cfg.connection_params(), ("smtp-relay.brevo.com", 587, "starttls"))
        conn = cfg.connection()
        self.assertEqual((conn.host, conn.username, conn.password, conn.use_tls),
                         ("smtp-relay.brevo.com", "8a1b2c@smtp-brevo.com", "xsmtpsib-secret", True))
        log = AuditLog.objects.get(action="settings.email_updated")
        self.assertNotIn("xsmtpsib-secret", str(log.after) + str(log.meta))
        # a blank password on a later save keeps the stored one
        self.client.post("/dashboard/settings/email/", self.form(password="", from_name="WS"))
        self.assertEqual(EmailSettings.active().connection().password, "xsmtpsib-secret")

    def test_password_required_first_time_and_custom_smtp_needs_host(self):
        self.client.force_login(self.super)
        r = self.client.post("/dashboard/settings/email/", self.form(password=""))
        self.assertIn("password", r.context["form"].errors)
        r = self.client.post("/dashboard/settings/email/", self.form(provider="smtp"))
        self.assertIn("host", r.context["form"].errors)

    def test_active_settings_are_used_for_all_email(self):
        from unittest import mock
        self.client.force_login(self.super)
        self.client.post("/dashboard/settings/email/", self.form(provider="gmail", username="ws@gmail.com",
                                                                 from_email="ws@gmail.com"))
        sent = []

        def fake_send(backend, messages):
            sent.extend((backend.host, backend.port, m.from_email, m.to[0]) for m in messages)
            return len(messages)

        with mock.patch("django.core.mail.backends.smtp.EmailBackend.send_messages", fake_send):
            self.client.get("/")
            r = self.post_json("/api/registration/email/send-otp/", {"email": "rahim@gmail.com"})
            self.assertEqual(r.status_code, 200, r.content)
            self.client.post("/dashboard/settings/email/", {"op": "test", "to": "me@example.org"})
        self.assertEqual(sent, [("smtp.gmail.com", 587, "WikiScholar <ws@gmail.com>", "rahim@gmail.com"),
                                ("smtp.gmail.com", 587, "WikiScholar <ws@gmail.com>", "me@example.org")])
        self.assertTrue(AuditLog.objects.filter(action="settings.email_tested", meta__ok=True).exists())

    def test_brevo_api_sends_over_https_without_username(self):
        import json
        from unittest import mock
        self.client.force_login(self.super)
        r = self.client.post("/dashboard/settings/email/", self.form(provider="brevo_api", username="",
                                                                     password="xkeysib-secret"))
        self.assertEqual(r.status_code, 302)
        calls = []

        class Resp:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return b'{"messageId": "<abc@smtp-relay.mailin.fr>"}'

        def fake_urlopen(req, timeout):
            calls.append((req.full_url, req.get_header("Api-key"), json.loads(req.data)))
            return Resp()

        with mock.patch("apps.notifications.backends.urllib.request.urlopen", fake_urlopen):
            self.client.post("/dashboard/settings/email/", {"op": "test", "to": "me@example.org"})
            r = self.post_json("/api/registration/email/send-otp/", {"email": "rahim@gmail.com"})
            self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual([(u, k, p["to"], p["sender"]) for u, k, p in calls], [
            ("https://api.brevo.com/v3/smtp/email", "xkeysib-secret", [{"email": "me@example.org"}],
             {"email": "noreply@wikimedia.org.bd", "name": "WikiScholar"}),
            ("https://api.brevo.com/v3/smtp/email", "xkeysib-secret", [{"email": "rahim@gmail.com"}],
             {"email": "noreply@wikimedia.org.bd", "name": "WikiScholar"})])
        self.assertTrue(AuditLog.objects.filter(action="settings.email_tested", meta__ok=True).exists())

    def test_changing_provider_needs_a_new_secret(self):
        self.client.force_login(self.super)
        self.client.post("/dashboard/settings/email/", self.form(provider="gmail", username="ws@gmail.com"))
        r = self.client.post("/dashboard/settings/email/", self.form(provider="brevo_api", password=""))
        self.assertIn("password", r.context["form"].errors)
        r = self.client.post("/dashboard/settings/email/", self.form(provider="brevo_api", password="xsmtpsib-x"))
        self.assertIn("xkeysib-", r.context["form"].errors["password"][0])
        r = self.client.post("/dashboard/settings/email/", self.form(provider="brevo_api", password="xkeysib-ok"))
        self.assertEqual(r.status_code, 302)
        # same provider again: blank keeps the saved key
        r = self.client.post("/dashboard/settings/email/", self.form(provider="brevo_api", password=""))
        self.assertEqual(r.status_code, 302)

    def test_reply_to_is_used_by_brevo_api_and_smtp(self):
        import json
        from unittest import mock
        self.client.force_login(self.super)
        self.client.post("/dashboard/settings/email/", self.form(provider="brevo_api", password="xkeysib-ok",
                                                                 reply_to="help@wikimedia.org.bd"))
        payloads = []

        class Resp:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return b"{}"

        def fake_urlopen(req, timeout):
            payloads.append(json.loads(req.data))
            return Resp()

        with mock.patch("apps.notifications.backends.urllib.request.urlopen", fake_urlopen):
            self.client.post("/dashboard/settings/email/", {"op": "test", "to": "me@example.org"})
            self.post_json("/api/registration/email/send-otp/", {"email": "rahim@gmail.com"})
        self.assertEqual([p.get("replyTo") for p in payloads], [{"email": "help@wikimedia.org.bd"}] * 2)

        self.client.post("/dashboard/settings/email/", self.form(reply_to="help@wikimedia.org.bd"))  # SMTP relay
        seen = []

        def fake_send(backend, messages):
            seen.extend(m.reply_to for m in messages)
            return len(messages)

        with mock.patch("django.core.mail.backends.smtp.EmailBackend.send_messages", fake_send):
            self.client.post("/dashboard/settings/email/", {"op": "test", "to": "me@example.org"})
        self.assertEqual(seen, [["help@wikimedia.org.bd"]])

    def test_brevo_api_error_message_is_shown(self):
        import io
        import urllib.error
        from unittest import mock
        self.client.force_login(self.super)
        self.client.post("/dashboard/settings/email/", self.form(provider="brevo_api", password="bad"))
        err = urllib.error.HTTPError("u", 401, "Unauthorized", {}, io.BytesIO(b'{"message": "Key not found"}'))
        with mock.patch("apps.notifications.backends.urllib.request.urlopen", side_effect=err):
            r = self.client.post("/dashboard/settings/email/", {"op": "test", "to": "me@example.org"}, follow=True)
        self.assertContains(r, "Brevo API error 401: Key not found")

    def test_dashboard_warns_when_email_is_not_delivered(self):
        from django.test import override_settings
        self.client.force_login(self.super)
        with override_settings(EMAIL_BACKEND="django.core.mail.backends.console.EmailBackend"):
            self.assertContains(self.client.get("/dashboard/"), "Emails are not being delivered")
        self.client.post("/dashboard/settings/email/", self.form())  # active Brevo settings
        self.assertNotContains(self.client.get("/dashboard/"), "Emails are not being delivered")


class SmsSettingsTests(WSTestCase):
    OK = {"statusCode": "200", "status": "Success", "trxnId": "BS8GLB0SEII1P2Z", "responseResult": "SMS Send Successfuly",
          "numberQty": "1", "success_Data": [{"mobNumber": "8801712345678", "trackingId": "TRX639", "sms_Count": 1,
                                             "lang_Type": "Text"}], "error_Data": []}
    FAIL = {"statusCode": "206", "status": "Failed", "trxnId": "A8XC", "responseResult": "Invalid Mobile Number",
            "numberQty": "", "success_Data": None,
            "error_Data": [{"res_Code": "206", "error": "Invalid Mobile Number", "failedNumbers": "", "errorParm": "88017"}]}

    def form(self, **over):
        data = {"op": "sms_save", "provider": "mimsms", "username": "sms@wikimedia.org.bd", "api_key": "KEY-123",
                "sender_name": "8809612444598", "api_url": "https://api.mimsms.com/api", "is_active": "on"}
        data.update(over)
        return data

    def fake_gateway(self, reply):
        """Patch urlopen; returns the list of (url, json body) the provider posted."""
        import io
        import json
        from unittest import mock
        calls = []

        class Resp(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *a): return False

        def urlopen(req, timeout=None):
            calls.append((req.full_url, json.loads(req.data)))
            return Resp(json.dumps(reply).encode())
        patcher = mock.patch("apps.notifications.providers.sms.urllib.request.urlopen", urlopen)
        patcher.start()
        self.addCleanup(patcher.stop)
        return calls

    def test_save_encrypts_key_and_audits_without_it(self):
        from apps.notifications.models import SmsSettings
        self.client.force_login(self.super)
        self.assertEqual(self.client.post("/dashboard/settings/email/", self.form()).status_code, 302)
        cfg = SmsSettings.active()
        self.assertNotIn("KEY-123", cfg.api_key_encrypted)
        self.assertEqual(cfg.api_key, "KEY-123")
        log = AuditLog.objects.get(action="settings.sms_updated")
        self.assertNotIn("KEY-123", str(log.after) + str(log.meta))
        self.client.post("/dashboard/settings/email/", self.form(api_key="", sender_name="WikiScholar"))
        cfg.refresh_from_db()
        self.assertEqual((cfg.api_key, cfg.sender_name), ("KEY-123", "WikiScholar"))

    def test_required_fields(self):
        self.client.force_login(self.super)
        r = self.client.post("/dashboard/settings/email/", self.form(username="", api_key="", sender_name=""))
        self.assertEqual(set(r.context["sms_form"].errors), {"username", "api_key", "sender_name"})
        self.assertEqual(self.client.get("/dashboard/settings/email/").status_code, 200)

    def test_bulk_sms_goes_through_mimsms_as_documented(self):
        self.register()
        self.client.force_login(self.super)
        self.client.post("/dashboard/settings/email/", self.form())
        calls = self.fake_gateway(self.OK)
        r = self.client.post("/dashboard/messages/compose/", {"name": "Test batch", "channel": "sms", "body": "Hello {name}", "confirm_count": 1})
        self.assertEqual(r.status_code, 302)
        url, body = calls[0]
        self.assertEqual(url, "https://api.mimsms.com/api/V2/SMS")
        self.assertEqual(body, {"userName": "sms@wikimedia.org.bd", "apiKey": "KEY-123", "senderName": "8809612444598",
                                "transactionType": "T", "campaignName": "WikiScholar",
                                "mobileNumber": "8801712345678", "message": "Hello Rahim Uddin"})
        log = NotificationLog.objects.get(kind="bulk", channel="sms")
        self.assertEqual((log.status, log.provider, log.provider_message_id), ("sent", "mimsms", "TRX639"))

    def test_gateway_error_is_recorded(self):
        self.register()
        self.client.force_login(self.super)
        self.client.post("/dashboard/settings/email/", self.form())
        self.fake_gateway(self.FAIL)
        self.client.post("/dashboard/messages/compose/", {"name": "Test batch", "channel": "sms", "body": "Hi", "confirm_count": 1})
        log = NotificationLog.objects.get(kind="bulk", channel="sms")
        self.assertEqual(log.status, "failed")
        self.assertEqual(log.error, "MiM SMS 206: Invalid Mobile Number")

    def test_test_sms_and_balance(self):
        self.client.force_login(self.super)
        self.client.post("/dashboard/settings/email/", self.form(is_active=""))  # works before activation
        calls = self.fake_gateway(self.OK)
        r = self.client.post("/dashboard/settings/email/", {"op": "sms_test", "phone": "+880 1812-345678"}, follow=True)
        self.assertContains(r, "Test SMS sent to 01812345678")
        self.assertEqual(calls[-1][1]["mobileNumber"], "8801812345678")
        self.assertTrue(AuditLog.objects.filter(action="settings.sms_tested", meta__ok=True).exists())
        # The shape the live API returns (2026-10)
        calls = self.fake_gateway({"statusCode": "200", "status": "Success", "trxnId": "P6", "message": "Success",
                                   "data": [{"balance": "205.5", "expair_Date": "26/01/2027"}]})
        r = self.client.post("/dashboard/settings/email/", {"op": "sms_balance"}, follow=True)
        self.assertContains(r, "MiM SMS balance: 205.5 (valid until 26/01/2027)")
        self.assertEqual(calls[-1], ("https://api.mimsms.com/api/V2/BalanceCheck",
                                     {"userName": "sms@wikimedia.org.bd", "apiKey": "KEY-123"}))
        # The shape in MiM's older docs
        self.fake_gateway({"statusCode": "200", "status": "Ok", "trxnId": "P7", "responseResult": "51"})
        r = self.client.post("/dashboard/settings/email/", {"op": "sms_balance"}, follow=True)
        self.assertContains(r, "MiM SMS balance: 51")
        # A 200 without a balance is an error, never an empty success message
        self.fake_gateway({"statusCode": "200", "status": "Success"})
        r = self.client.post("/dashboard/settings/email/", {"op": "sms_balance"}, follow=True)
        self.assertContains(r, "Balance check failed: MiM SMS sent no balance")

    def test_only_super_admin_and_inactive_falls_back_to_env(self):
        from apps.notifications import services as notify
        from apps.notifications.models import Channel
        self.client.force_login(self.admin)
        self.assertEqual(self.client.post("/dashboard/settings/email/", self.form()).status_code, 403)
        self.assertEqual(notify.provider_for(Channel.SMS).name, "console-sms")
