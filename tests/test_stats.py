from datetime import date, datetime, timedelta

from django.http import QueryDict
from django.utils import timezone

from apps.core.models import Admin, Role
from apps.dashboard import charts, stats
from apps.registration.models import Student

from .base import WSTestCase

TODAY = date(2026, 11, 22)  # a Sunday


def q(s=""):
    return QueryDict(s)


def at(d, hour=10):
    return datetime(d.year, d.month, d.day, hour, 0, tzinfo=timezone.get_default_timezone())


class ResolveTests(WSTestCase):
    def test_default_is_last_28_days(self):
        p = stats.resolve(q(), TODAY)
        self.assertEqual((p.start, p.end, p.range, p.by), (TODAY - timedelta(days=27), TODAY, "28d", "day"))
        self.assertFalse(p.comparing)

    def test_presets(self):
        cases = {
            "today": (TODAY, TODAY), "yesterday": (date(2026, 11, 21),) * 2,
            "7d": (date(2026, 11, 16), TODAY), "90d": (date(2026, 8, 25), TODAY),
            "this_month": (date(2026, 11, 1), TODAY), "last_month": (date(2026, 10, 1), date(2026, 10, 31)),
            "this_year": (date(2026, 1, 1), TODAY),
        }
        for key, (start, end) in cases.items():
            p = stats.resolve(q(f"range={key}"), TODAY)
            self.assertEqual((p.start, p.end), (start, end), key)
        p = stats.resolve(q("range=all"), TODAY, first_day=date(2026, 3, 1))
        self.assertEqual((p.start, p.by), (date(2026, 3, 1), "month"))

    def test_custom_range_swapped_and_clamped(self):
        p = stats.resolve(q("range=custom&from=30/12/2026&to=01/11/2026"), TODAY)
        self.assertEqual((p.start, p.end), (date(2026, 11, 1), TODAY))
        # dates without range= mean custom
        p = stats.resolve(q("from=2026-10-05&to=2026-10-10"), TODAY)
        self.assertEqual((p.range, p.start, p.end), ("custom", date(2026, 10, 5), date(2026, 10, 10)))

    def test_grouping(self):
        self.assertEqual(stats.resolve(q("range=90d"), TODAY).by, "week")
        self.assertEqual(stats.resolve(q("range=this_year"), TODAY).by, "month")
        self.assertEqual(stats.resolve(q("range=90d&by=day"), TODAY).by, "day")
        self.assertEqual(stats.resolve(q("by=bogus"), TODAY).by_choice, "")

    def test_compare_periods(self):
        p = stats.resolve(q("range=7d&cmp=prev"), TODAY)
        self.assertEqual((p.cmp_start, p.cmp_end), (date(2026, 11, 9), date(2026, 11, 15)))
        p = stats.resolve(q("range=this_month&cmp=year"), TODAY)
        self.assertEqual((p.cmp_start, p.cmp_end), (date(2025, 11, 1), date(2025, 11, 22)))
        p = stats.resolve(q("range=7d&cmp=custom&cmp_from=10/01/2026&cmp_to=01/01/2026"), TODAY)
        self.assertEqual((p.cmp_start, p.cmp_end), (date(2026, 1, 1), date(2026, 1, 10)))
        p = stats.resolve(q("range=7d&cmp=custom"), TODAY)  # no dates: no comparison
        self.assertFalse(p.comparing)
        self.assertEqual(p.cmp, "")

    def test_leap_day_last_year(self):
        p = stats.resolve(q("from=29/02/2028&to=29/02/2028&cmp=year"), date(2028, 3, 1))
        self.assertEqual(p.cmp_start, date(2027, 2, 28))

    def test_filters_parsed(self):
        p = stats.resolve(q("region=1&region=x&district=4&district=4&class=8&class=12"), TODAY)
        self.assertEqual((p.regions, p.districts, p.classes), (["1"], ["4"], ["8"]))


class CountingTests(WSTestCase):
    def setUp(self):
        super().setUp()
        self.a = self.register("a@gmail.com", gender="female", current_class="6")
        self.b = self.register("b@gmail.com", phone="01712345679", guardian_relation="other",
                               guardian_relation_other=" Uncle ", heard_from="banner")
        self.c = self.register("c@gmail.com", phone="01712345670", district=self.jessore.pk, thana=self.sharsha.pk,
                               school_id=None, school_name="Sharsha Pilot High School")
        self.date(self.a, date(2026, 11, 20))   # Friday
        self.date(self.b, date(2026, 11, 20), hour=23)
        self.date(self.c, date(2026, 11, 2))    # Monday, two weeks before

    def date(self, summary, d, hour=10):
        Student.objects.filter(wikischolar_id=summary["wikischolar_id"]).update(created_at=at(d, hour))

    def test_timeseries_fills_empty_buckets(self):
        qs = stats.filtered(stats.resolve(q(), TODAY))
        days = stats.timeseries(qs, date(2026, 11, 18), date(2026, 11, 21), "day")
        self.assertEqual(days, [(date(2026, 11, 18), 0), (date(2026, 11, 19), 0),
                                (date(2026, 11, 20), 2), (date(2026, 11, 21), 0)])
        weeks = stats.timeseries(qs, date(2026, 11, 1), TODAY, "week")
        self.assertEqual(weeks, [(date(2026, 10, 26), 0), (date(2026, 11, 2), 1), (date(2026, 11, 9), 0),
                                 (date(2026, 11, 16), 2)])
        months = stats.timeseries(qs, date(2026, 10, 1), TODAY, "month")
        self.assertEqual(months, [(date(2026, 10, 1), 0), (date(2026, 11, 1), 3)])

    def test_local_day_boundary(self):
        # 23:00 Dhaka time on the 20th is still the 20th
        qs = stats.filtered(stats.resolve(q(), TODAY))
        self.assertEqual(stats.in_period(qs, date(2026, 11, 20), date(2026, 11, 20)).count(), 2)

    def test_filters_and_archived(self):
        p = stats.resolve(q(f"range=this_month&region={self.dhaka.pk}"), TODAY)
        self.assertEqual(stats.kpis(stats.filtered(p), p.start, p.end)["total"], 2)
        p = stats.resolve(q(f"range=this_month&district={self.jessore.pk}"), TODAY)
        self.assertEqual(stats.kpis(stats.filtered(p), p.start, p.end)["total"], 1)
        p = stats.resolve(q("range=this_month&class=6"), TODAY)
        self.assertEqual(stats.kpis(stats.filtered(p), p.start, p.end)["total"], 1)
        Student.objects.get(wikischolar_id=self.a["wikischolar_id"]).soft_delete()
        p = stats.resolve(q("range=this_month"), TODAY)
        self.assertEqual(stats.kpis(stats.filtered(p), p.start, p.end)["total"], 2)

    def test_kpis_and_breakdowns(self):
        p = stats.resolve(q("range=this_month&cmp=prev"), TODAY)
        base = stats.filtered(p)
        k = stats.kpis(base, p.start, p.end)
        self.assertEqual((k["total"], k["female"], k["peak"], k["peak_day"]), (3, 1, 2, date(2026, 11, 20)))
        b = stats.breakdowns(p, stats.in_period(base, p.start, p.end), stats.in_period(base, p.cmp_start, p.cmp_end),
                             lambda **kw: None)
        by = {r["key"]: r for r in b["gender"]}
        self.assertEqual((by["male"]["n"], by["female"]["n"], by["male"]["prev"]), (2, 1, 0))
        self.assertEqual(by["male"]["change"], {"text": "new", "dir": "new"})
        self.assertEqual([(r["label"], r["n"]) for r in b["other_relations"]], [("Uncle", 1)])
        self.assertEqual({r["label"]: r["n"] for r in b["regions"]}, {"Dhaka": 2, "Khulna": 1})
        self.assertEqual({r["label"]: r["n"] for r in b["weekdays"] if r["n"]}, {"Friday": 2, "Monday": 1})
        self.assertEqual({r["key"]: r["n"] for r in b["hours"] if r["n"]}, {10: 2, 23: 1})
        self.assertIsNone(b["thanas"])

    def test_change(self):
        self.assertEqual(stats.change(15, 10), {"text": "+50%", "dir": "up"})
        self.assertEqual(stats.change(5, 10), {"text": "-50%", "dir": "down"})
        self.assertEqual(stats.change(0, 0), {"text": "±0%", "dir": "flat"})
        self.assertEqual(stats.change(40.0, 37.5, points=True), {"text": "+2.5 pts", "dir": "up"})


class PageTests(WSTestCase):
    def test_permissions(self):
        self.assertEqual(self.client.get("/dashboard/stats/").status_code, 302)
        organiser = Admin.objects.create_user(email="org@ws.test", password="x-Strong-pass-123",
                                              full_name="Org", role=Role.ORGANISER)
        for user in (organiser, self.viewer, self.admin, self.super):
            self.client.force_login(user)
            self.assertEqual(self.client.get("/dashboard/stats/").status_code, 200, user.role)

    def test_renders_empty(self):
        self.client.force_login(self.viewer)
        r = self.client.get("/dashboard/stats/?range=all&cmp=prev")
        self.assertContains(r, "No registrations in this period.")

    def test_renders_with_data_compare_and_filters(self):
        self.register()
        self.client.force_login(self.viewer)
        r = self.client.get(f"/dashboard/stats/?range=7d&cmp=year&district={self.gazipur.pk}&class=8&by=day")
        self.assertContains(r, "Gazipur")
        self.assertContains(r, "Tongi")  # one district picked: its thanas
        self.assertContains(r, "compared with")
        self.assertContains(r, "/dashboard/students/?")
        r = self.client.get("/dashboard/stats/?range=this_year&cmp=custom&cmp_from=01/01/2025&cmp_to=31/12/2025")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Registrations over time")

    def test_organiser_gets_no_student_links(self):
        self.register()
        organiser = Admin.objects.create_user(email="org@ws.test", password="x-Strong-pass-123",
                                              full_name="Org", role=Role.ORGANISER)
        self.client.force_login(organiser)
        r = self.client.get("/dashboard/stats/")
        self.assertContains(r, "Gazipur")
        self.assertNotContains(r, "/dashboard/students/")
        self.assertNotContains(r, "Tongi Government High School")

    def test_overview_links_to_stats(self):
        self.client.force_login(self.viewer)
        self.assertContains(self.client.get("/dashboard/"), "/dashboard/stats/")


class ChartTests(WSTestCase):
    def test_nice_scale(self):
        self.assertEqual(charts.nice_scale(0), (1, [0, 1]))
        self.assertEqual(charts.nice_scale(7), (8, [0, 2, 4, 6, 8]))
        self.assertEqual(charts.nice_scale(130), (150, [0, 50, 100, 150]))

    def test_line_chart_compare_lengths(self):
        cur = [(date(2026, 11, d), d) for d in (1, 2, 3)]
        prev = [(date(2026, 10, d), 1) for d in (1, 2, 3, 4)]
        c = charts.line_chart(cur, prev, str)
        self.assertEqual(len(c["columns"]), 4)
        self.assertEqual(c["cur"].split()[0], "0.0,66.67")
        self.assertEqual(len(c["prev"].split()), 4)
        single = charts.line_chart([(date(2026, 11, 1), 5)])
        self.assertEqual(single["dots"][0]["left"], 50.0)
