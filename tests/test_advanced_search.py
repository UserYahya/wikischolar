"""Advanced (conditional) search on the Students and Schools lists (apps/dashboard/advanced.py)."""
import json
from urllib.parse import quote

from apps.dashboard import advanced
from apps.reference.models import School
from apps.registration.models import Student

from .base import WSTestCase


def adv(*groups, match="all"):
    return json.dumps({"match": match, "groups": [{"match": m, "conditions": c} for m, c in groups]})


def cond(field, op, value=None):
    return {"field": field, "op": op, **({} if value is None else {"value": value})}


class EngineTests(WSTestCase):
    def setUp(self):
        super().setUp()
        self.a = Student.objects.get(wikischolar_id=self.register(email="a@gmail.com", current_class="8")["wikischolar_id"])
        self.b = Student.objects.get(wikischolar_id=self.register(email="b@gmail.com", current_class="9",
                                                                     gender="female", student_name="Rina Akter",
                                                                     updates_opt_in=False)["wikischolar_id"])

    def ids(self, query):
        q, problems, _ = advanced.parse("students", query)
        return set(Student.objects.filter(q).values_list("pk", flat=True)), problems

    def test_text_choice_bool_and_number_operators(self):
        self.assertEqual(self.ids(adv(("all", [cond("student_name", "contains", "rina")])))[0], {self.b.pk})
        self.assertEqual(self.ids(adv(("all", [cond("student_name", "not_contains", "rina")])))[0], {self.a.pk})
        self.assertEqual(self.ids(adv(("all", [cond("student_name", "starts", "RAHIM")])))[0], {self.a.pk})
        self.assertEqual(self.ids(adv(("all", [cond("section", "empty")])))[0], {self.a.pk, self.b.pk})
        self.assertEqual(self.ids(adv(("all", [cond("gender", "in", ["female"])])))[0], {self.b.pk})
        self.assertEqual(self.ids(adv(("all", [cond("current_class", "not_in", ["8"])])))[0], {self.b.pk})
        self.assertEqual(self.ids(adv(("all", [cond("updates_opt_in", "no")])))[0], {self.b.pk})
        self.assertEqual(self.ids(adv(("all", [cond("district", "in", [self.gazipur.pk])])))[0], {self.a.pk, self.b.pk})
        self.assertEqual(self.ids(adv(("all", [cond("region", "not_in", [self.dhaka.pk])])))[0], set())
        today = self.a.created_at.strftime("%d/%m/%Y")
        self.assertEqual(self.ids(adv(("all", [cond("created_at", "between", [today, today])])))[0], {self.a.pk, self.b.pk})
        self.assertEqual(self.ids(adv(("all", [cond("created_at", "lt", today)])))[0], set())

    def test_all_and_any_inside_and_across_groups(self):
        rina, class8 = cond("student_name", "contains", "rina"), cond("current_class", "in", ["8"])
        self.assertEqual(self.ids(adv(("all", [rina, class8])))[0], set())
        self.assertEqual(self.ids(adv(("any", [rina, class8])))[0], {self.a.pk, self.b.pk})
        self.assertEqual(self.ids(adv(("all", [rina]), ("all", [class8]), match="any"))[0], {self.a.pk, self.b.pk})
        self.assertEqual(self.ids(adv(("all", [rina]), ("all", [class8]), match="all"))[0], set())

    def test_through_the_school(self):
        School.objects.filter(pk=self.school.pk).update(management="government", eiin="100014")
        self.assertEqual(self.ids(adv(("all", [cond("school__management", "in", ["government"])])))[0],
                         {self.a.pk, self.b.pk})
        self.assertEqual(self.ids(adv(("all", [cond("school__eiin", "eq", "999999")])))[0], set())

    def test_invalid_conditions_are_left_out_never_run(self):
        ids, problems = self.ids(adv(("all", [cond("password", "eq", "x"), cond("gender", "contains", "f"),
                                              cond("gender", "in", ["robot"]), cond("current_class", "in", []),
                                              cond("created_at", "eq", "not a date"),
                                              cond("student_name", "contains", "x" * 300)])))
        self.assertEqual(ids, {self.a.pk, self.b.pk})  # nothing valid left: no filter
        self.assertEqual(len(problems), 6)
        self.assertIn("“password” can't be searched", problems[0])
        self.assertEqual(advanced.normalize("students", "not json"), "")
        self.assertEqual(advanced.normalize("students", '["a list"]'), "")

    def test_limits(self):
        many = adv(*[("all", [cond("gender", "in", ["male"])])] * 12)
        self.assertIn("Only the first 10 groups are used.", advanced.parse("students", many)[1])
        long = adv(("all", [cond("gender", "in", ["male"])] * 25))
        self.assertIn("Group 1: only the first 20 conditions are used.", advanced.parse("students", long)[1])

    def test_describe(self):
        text = advanced.describe("students", adv(("any", [cond("gender", "in", ["female"]), cond("current_class", "in", ["8", "9"])]),
                                                 ("all", [cond("district", "in", [self.gazipur.pk])])))
        self.assertEqual(text, "(Gender is any of Female OR Class is any of Class 8, Class 9) AND District is any of Gazipur")


class StudentListTests(EngineTests):
    def test_list_export_and_message_composer_follow_the_advanced_search(self):
        query = quote(adv(("all", [cond("student_name", "contains", "rina")])))
        self.client.force_login(self.admin)
        r = self.client.get(f"/dashboard/students/?adv={query}")
        self.assertEqual(r.context["count"], 1)
        self.assertContains(r, "Student name contains “rina”")
        r = self.client.get(f"/dashboard/students/export.csv?adv={query}")
        body = b"".join(r.streaming_content).decode()
        self.assertIn(self.b.wikischolar_id, body)
        self.assertNotIn(self.a.wikischolar_id, body)
        r = self.client.get(f"/dashboard/messages/compose/?adv={query}")
        self.assertContains(r, "Advanced search")
        self.assertContains(r, "Student name contains “rina”")

    def test_problems_are_shown_and_viewers_can_search(self):
        self.client.force_login(self.viewer)
        r = self.client.get("/dashboard/students/?adv=" + quote(adv(("all", [cond("nope", "eq", "x")]))))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "“nope” can&#x27;t be searched")
        self.assertEqual(r.context["count"], 2)


class SchoolListTests(WSTestCase):
    def test_schools_by_government_data_and_number_of_students(self):
        School.objects.filter(pk=self.school.pk).update(management="government", area_status="city_corporation")
        other = School.objects.create(name="Kaliakair Model School", district=self.gazipur, thana=self.kaliakair,
                                      verification_status="verified", management="non_government")
        self.register()
        self.client.force_login(self.viewer)
        query = adv(("all", [cond("management", "in", ["government"]), cond("area_status", "in", ["city_corporation"])]))
        r = self.client.get("/dashboard/schools/?adv=" + quote(query))
        self.assertEqual([s.pk for s in r.context["page"]], [self.school.pk])
        r = self.client.get("/dashboard/schools/?adv=" + quote(adv(("all", [cond("students", "ge", 1)]))))
        self.assertEqual([s.pk for s in r.context["page"]], [self.school.pk])
        r = self.client.get("/dashboard/schools/?adv=" + quote(adv(("all", [cond("students", "eq", 0)]))))
        self.assertEqual([s.pk for s in r.context["page"]], [other.pk])
        self.assertContains(r, "Number of students = 0")


class SavedSearchTests(WSTestCase):
    def setUp(self):
        super().setUp()
        from apps.core.models import Admin, Role
        self.other = Admin.objects.create_user(email="other@ws.test", password="x-Strong-pass-123",
                                               full_name="Other Admin", role=Role.ADMIN)
        self.register(email="a@gmail.com")
        self.register(email="b@gmail.com", gender="female", student_name="Rina Akter")
        self.query = adv(("all", [cond("gender", "in", ["female"])]))

    def save(self, **over):
        data = {"entity": "students", "name": "Girls", "description": "All girls", "adv": self.query, **over}
        return self.client.post("/dashboard/searches/save/", data)

    def test_save_load_update_and_delete(self):
        from apps.core.models import AuditLog
        from apps.dashboard.models import SavedSearch
        self.client.force_login(self.admin)
        r = self.save()
        s = SavedSearch.objects.get()
        self.assertRedirects(r, f"/dashboard/students/?saved={s.pk}")
        self.assertEqual((s.name, s.created_by, s.query["groups"][0]["conditions"][0]["field"]), ("Girls", self.admin, "gender"))
        r = self.client.get(f"/dashboard/students/?saved={s.pk}")
        self.assertEqual(r.context["count"], 1)
        self.assertContains(r, "Running saved search <strong>Girls</strong>")
        # export and the message composer follow the saved search too
        body = b"".join(self.client.get(f"/dashboard/students/export.csv?saved={s.pk}").streaming_content).decode()
        self.assertEqual(body.count("WS-"), 1)
        self.assertEqual(self.save().status_code, 302)  # same name again: refused
        self.assertEqual(SavedSearch.objects.count(), 1)
        boys = adv(("all", [cond("gender", "in", ["male"])]))
        self.client.post("/dashboard/searches/save/", {"entity": "students", "id": s.pk, "adv": boys})
        s.refresh_from_db()
        self.assertEqual((s.name, s.query["groups"][0]["conditions"][0]["value"], s.updated_by), ("Girls", ["male"], self.admin))
        self.client.post(f"/dashboard/searches/{s.pk}/delete/")
        self.assertFalse(SavedSearch.objects.exists())
        self.assertTrue(SavedSearch.all_objects.filter(pk=s.pk, is_deleted=True).exists())
        self.assertEqual(list(AuditLog.objects.filter(action__startswith="search.").order_by("pk")
                              .values_list("action", flat=True)), ["search.saved", "search.updated", "search.deleted"])

    def test_shared_with_everyone_but_only_the_owner_or_a_super_admin_changes_it(self):
        from apps.dashboard.models import SavedSearch
        self.client.force_login(self.admin)
        self.save()
        s = SavedSearch.objects.get()
        for user in (self.other, self.viewer):
            self.client.force_login(user)
            r = self.client.get(f"/dashboard/students/?saved={s.pk}")
            self.assertEqual(r.context["count"], 1)
            self.assertNotContains(r, "Delete saved search")
            self.assertContains(self.client.get("/dashboard/searches/"), "Girls")
            self.assertEqual(self.client.post(f"/dashboard/searches/{s.pk}/delete/").status_code, 403)
            self.assertEqual(self.client.post("/dashboard/searches/save/", {"entity": "students", "id": s.pk,
                                                                            "adv": self.query}).status_code, 403)
        self.client.force_login(self.super)
        self.assertContains(self.client.get(f"/dashboard/students/?saved={s.pk}"), "Delete saved search")
        self.client.post(f"/dashboard/searches/{s.pk}/delete/")
        self.assertFalse(SavedSearch.objects.exists())

    def test_a_viewer_can_save_their_own(self):
        from apps.dashboard.models import SavedSearch
        self.client.force_login(self.viewer)
        self.save(name="Viewer's girls")
        self.assertEqual(SavedSearch.objects.get().created_by, self.viewer)

    def test_empty_or_bad_queries_and_names_are_refused(self):
        from apps.dashboard.models import SavedSearch
        self.client.force_login(self.admin)
        self.save(adv=adv(("all", [cond("nope", "eq", "x")])))
        self.save(name="")
        self.save(name="মেয়েরা")
        self.assertFalse(SavedSearch.objects.exists())
        self.assertEqual(self.client.post("/dashboard/searches/save/", {"entity": "admins", "name": "x",
                                                                        "adv": self.query}).status_code, 403)

    def test_a_stale_field_is_dropped_when_loaded(self):
        from apps.dashboard.models import SavedSearch
        s = SavedSearch.objects.create(entity="students", name="Old", created_by=self.admin, query={
            "match": "all", "groups": [{"match": "all", "conditions": [cond("date_of_birth", "lt", "01/01/2012"),
                                                                       cond("gender", "in", ["female"])]}]})
        self.client.force_login(self.admin)
        r = self.client.get(f"/dashboard/students/?saved={s.pk}")
        self.assertEqual(r.context["count"], 1)
        self.assertContains(r, "Gender is any of Female")

    def test_school_searches_are_kept_apart(self):
        from apps.dashboard.models import SavedSearch
        self.client.force_login(self.admin)
        self.client.post("/dashboard/searches/save/", {"entity": "schools", "name": "Busy schools",
                                                       "adv": adv(("all", [cond("students", "ge", 1)]))})
        s = SavedSearch.objects.get(entity="schools")
        r = self.client.get(f"/dashboard/schools/?saved={s.pk}")
        self.assertEqual([x.pk for x in r.context["page"]], [self.school.pk])
        r = self.client.get(f"/dashboard/students/?saved={s.pk}")  # not a student search: ignored
        self.assertEqual(r.context["count"], 2)


class SchoolExportTests(WSTestCase):
    """Schools → Export CSV: exactly the schools the list shows, quick filters, advanced and saved search."""

    def setUp(self):
        super().setUp()
        School.objects.filter(pk=self.school.pk).update(eiin="100014", management="government", mpo="no",
                                                         area_status="city_corporation", division="Dhaka")
        self.other = School.objects.create(name="Kaliakair Model School", district=self.gazipur, thana=self.kaliakair,
                                           verification_status="verified", management="non_government", eiin="100015")
        self.register()

    def export(self, query=""):
        r = self.client.get("/dashboard/schools/export.csv" + query)
        self.assertEqual(r.status_code, 200)
        self.assertIn('filename="schools-', r["Content-Disposition"])
        rows = b"".join(r.streaming_content).decode("utf-8-sig").splitlines()
        return rows[0].split(","), [line.split(",") for line in rows[1:]]

    def test_exports_what_the_advanced_search_shows(self):
        from apps.core.models import AuditLog
        self.client.force_login(self.viewer)
        query = "?adv=" + quote(adv(("all", [cond("management", "in", ["government"])])))
        self.assertContains(self.client.get("/dashboard/schools/" + query), "/dashboard/schools/export.csv?adv=")
        header, rows = self.export(query)
        self.assertEqual(header[:5], ["school_id", "eiin", "name", "status", "source"])
        self.assertEqual(len(rows), 1)
        row = dict(zip(header, rows[0]))
        self.assertEqual((row["eiin"], row["name"], row["management"], row["mpo"], row["area_status"], row["students"],
                          row["district"], row["thana"], row["division"]),
                         ("100014", "TONGI GOVERNMENT HIGH SCHOOL", "Government", "No", "City corporation", "1",
                          "Gazipur", "Tongi", "Dhaka"))
        log = AuditLog.objects.get(action="schools.exported")
        self.assertEqual(log.meta["rows"], 1)
        self.assertIn("adv", log.meta["filter"])

    def test_quick_filters_and_saved_searches(self):
        from apps.dashboard.models import SavedSearch
        self.client.force_login(self.admin)
        self.assertEqual(len(self.export()[1]), 2)
        self.assertEqual([r[1] for r in self.export(f"?thana={self.kaliakair.pk}&district={self.gazipur.pk}")[1]], ["100015"])
        self.assertEqual([r[1] for r in self.export("?q=100015")[1]], ["100015"])
        s = SavedSearch.objects.create(entity="schools", name="Non-govt", created_by=self.admin, query={
            "match": "all", "groups": [{"match": "all", "conditions": [cond("management", "in", ["non_government"])]}]})
        self.assertEqual([r[1] for r in self.export(f"?saved={s.pk}")[1]], ["100015"])

    def test_student_export_has_the_school_government_data(self):
        self.client.force_login(self.admin)
        body = b"".join(self.client.get("/dashboard/students/export.csv").streaming_content).decode("utf-8-sig")
        header, row = [line.split(",") for line in body.splitlines()[:2]]
        data = dict(zip(header, row))
        self.assertEqual((data["school_eiin"], data["school_management"]), ("100014", "Government"))
