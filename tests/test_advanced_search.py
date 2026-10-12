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
