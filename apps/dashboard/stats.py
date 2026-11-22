"""The Statistics page's numbers: a date range (with an optional period to compare it with), the
region/district/class filters, and grouped counts of the students who registered in it.

Everything here is counts only (no names, contact details or schools), so an Organiser can see it.
Days and hours are Bangladesh time (Asia/Dhaka, UTC+6, no daylight saving), set explicitly on every
date boundary, Trunc* and Extract* so it doesn't depend on the active timezone.
Archived students are never counted (Student.objects hides them).
"""
import json
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo
from urllib.parse import urlencode

from django.db.models import Count, Q
from django.db.models.functions import (ExtractHour, ExtractIsoWeekDay, Lower, Trim, TruncDate, TruncHour,
                                        TruncMonth, TruncWeek)
from django.utils import timezone

from apps.core.utils import DATE_FORMAT, parse_date
from apps.reference.models import District, Region, Thana
from apps.registration.choices import CLASS_CHOICES, CLASS_VALUES, FilledBy, Gender, GuardianRelation, HeardFrom
from apps.registration.models import Student

DEFAULT_RANGE = "28d"
RANGES = {
    "today": "Today", "yesterday": "Yesterday", "7d": "Last 7 days", "28d": "Last 28 days",
    "30d": "Last 30 days", "90d": "Last 90 days", "this_month": "This month", "last_month": "Last month",
    "this_year": "This year", "all": "All time", "custom": "Custom range",
}
COMPARES = {"": "Don't compare", "prev": "Previous period", "year": "Same period last year",
            "custom": "Custom period"}
DHAKA = ZoneInfo("Asia/Dhaka")
GROUPINGS = {"": "Auto", "hour": "Hour", "day": "Day", "week": "Week", "month": "Month"}
MAX_HOURLY_DAYS = 7  # longer ranges have too many hours to chart
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
TOP_DISTRICTS = 15
TOP_OTHER_RELATIONS = 10


@dataclass
class Period:
    start: date
    end: date
    range: str = DEFAULT_RANGE
    by: str = "day"          # the grouping actually used
    by_choice: str = ""      # what was asked for ("" = auto)
    cmp: str = ""
    cmp_start: date | None = None
    cmp_end: date | None = None
    regions: list = field(default_factory=list)
    districts: list = field(default_factory=list)
    classes: list = field(default_factory=list)

    @property
    def days(self):
        return (self.end - self.start).days + 1

    @property
    def comparing(self):
        return self.cmp_start is not None

    @property
    def cmp_days(self):
        return (self.cmp_end - self.cmp_start).days + 1 if self.comparing else 0


def _ints(values):
    return [v for v in dict.fromkeys(str(v).strip() for v in values) if v.isdigit()]


def _shift_year(d, years=-1):
    try:
        return d.replace(year=d.year + years)
    except ValueError:  # 29 February
        return d.replace(year=d.year + years, day=28)


def _ordered(a, b):
    return (a, b) if a <= b else (b, a)


def _preset(key, today, first_day):
    if key == "today":
        return today, today
    if key == "yesterday":
        return today - timedelta(days=1), today - timedelta(days=1)
    if key in ("7d", "28d", "30d", "90d"):
        return today - timedelta(days=int(key[:-1]) - 1), today
    if key == "this_month":
        return today.replace(day=1), today
    if key == "last_month":
        end = today.replace(day=1) - timedelta(days=1)
        return end.replace(day=1), end
    if key == "this_year":
        return today.replace(month=1, day=1), today
    if key == "all":
        return min(first_day or today, today), today
    raise KeyError(key)


def auto_grouping(days):
    return "hour" if days == 1 else "day" if days <= 62 else "week" if days <= 26 * 7 else "month"


def resolve(get, today, first_day=None):
    """The period, compare period and filters asked for in the query string. Anything missing or
    invalid falls back to a sensible default, so any URL renders."""
    rng = get.get("range", "").strip()
    if rng not in RANGES:
        rng = "custom" if (get.get("from") or get.get("to")) else DEFAULT_RANGE
    if rng == "custom":
        start = parse_date(get.get("from")) or first_day or today
        end = parse_date(get.get("to")) or today
    else:
        start, end = _preset(rng, today, first_day)
    start, end = _ordered(min(start, today), min(end, today))

    by_choice = get.get("by", "").strip()
    by_choice = by_choice if by_choice in GROUPINGS else ""
    if by_choice == "hour" and (end - start).days + 1 > MAX_HOURLY_DAYS:
        by_choice = ""
    p = Period(start, end, rng, by_choice or auto_grouping((end - start).days + 1), by_choice)

    cmp = get.get("cmp", "").strip()
    if cmp == "prev":
        p.cmp_end = start - timedelta(days=1)
        p.cmp_start = p.cmp_end - timedelta(days=p.days - 1)
    elif cmp == "year":
        p.cmp_start, p.cmp_end = _shift_year(start), _shift_year(end)
    elif cmp == "custom":
        a, b = parse_date(get.get("cmp_from")), parse_date(get.get("cmp_to"))
        if a or b:
            p.cmp_start, p.cmp_end = _ordered(a or b, b or a)
    p.cmp = cmp if p.comparing else ""

    p.regions = _ints(get.getlist("region"))
    p.districts = _ints(get.getlist("district"))
    p.classes = [c for c in dict.fromkeys(get.getlist("class")) if c in CLASS_VALUES]
    return p


def first_registration_day():
    first = Student.objects.order_by("created_at").values_list("created_at", flat=True).first()
    return timezone.localdate(first, DHAKA) if first else None


def filtered(p):
    """All (alive) students matching the filters, in any period. Region and district are combined
    the same way as on the student list (both must match), so the links there show the same students."""
    qs = Student.objects.order_by()
    if p.districts:
        qs = qs.filter(district_id__in=p.districts)
    if p.regions:
        qs = qs.filter(district__region_id__in=p.regions)
    if p.classes:
        qs = qs.filter(current_class__in=p.classes)
    return qs


def day_start(d):
    """Midnight at the start of a Bangladesh day, as an aware datetime."""
    return datetime.combine(d, time(), tzinfo=DHAKA)


def in_period(qs, start, end):
    return qs.filter(created_at__gte=day_start(start), created_at__lt=day_start(end + timedelta(days=1)))


# ---- Over time ----------------------------------------------------------------------------- #
def _bucket_start(d, by):
    if by == "hour":
        return datetime.combine(d, time())  # naive Bangladesh time
    if by == "week":
        return d - timedelta(days=d.weekday())
    if by == "month":
        return d.replace(day=1)
    return d


def _next_bucket(d, by):
    if by == "hour":
        return d + timedelta(hours=1)
    if by == "week":
        return d + timedelta(days=7)
    if by == "month":
        return (d.replace(day=28) + timedelta(days=4)).replace(day=1)
    return d + timedelta(days=1)


def bucket_label(d, by, short=False, one_day=True):
    """Text for a bucket. Hours: "14:00" on the axis ("22 Nov" at midnight when the range has several
    days); the tooltip/table text names the hour range, e.g. "22 Nov, 14:00–15:00"."""
    if by == "hour":
        if short:
            return f"{d:%H}:00" if one_day or d.hour else f"{d.day} {d:%b}"
        return f"{d.day} {d:%b}, {d:%H}:00–{(d + timedelta(hours=1)):%H}:00"
    if by == "month":
        return d.strftime("%b %Y") if not short else d.strftime("%b %y")
    label = f"{d.day} {d.strftime('%b')}"
    return f"w/c {label}" if by == "week" and not short else label


def timeseries(qs, start, end, by, until=None):
    """[(bucket start, count)] covering start..end, empty buckets included. Buckets are dates, or
    naive Bangladesh-time datetimes for hours. The first and last week/month may be partial (only the
    days inside the range are counted). `until` (a naive Bangladesh datetime) stops the series at that
    moment, so today's hours end at the current hour instead of showing the rest of the day as 0."""
    trunc = {"hour": TruncHour, "day": TruncDate, "week": TruncWeek, "month": TruncMonth}[by]("created_at", tzinfo=DHAKA)
    counts = {}
    for k, n in in_period(qs, start, end).annotate(b=trunc).values_list("b").annotate(n=Count("id")):
        if by == "hour":
            k = k.astimezone(DHAKA).replace(tzinfo=None)
        elif isinstance(k, datetime):
            k = k.date()
        counts[k] = counts.get(k, 0) + n
    out, b = [], _bucket_start(start, by)
    last = datetime.combine(end, time(23)) if by == "hour" else end
    while b <= last and (until is None or by != "hour" or b <= until):
        out.append((b, counts.get(b, 0)))
        b = _next_bucket(b, by)
    return out


def busiest(series):
    """(bucket, count) of the busiest bucket (the earliest on a tie), or (None, 0)."""
    best = max(series, key=lambda r: r[1], default=(None, 0))
    return best if best[1] else (None, 0)


def daily_peak(qs, start, end):
    row = (in_period(qs, start, end).annotate(d=TruncDate("created_at", tzinfo=DHAKA)).values_list("d")
           .annotate(n=Count("id")).order_by("-n", "d").first())
    return row if row else (None, 0)


# ---- Headline figures ------------------------------------------------------------------------ #
def kpis(qs, start, end):
    s = in_period(qs, start, end).aggregate(
        total=Count("id"),
        female=Count("id", filter=Q(gender=Gender.FEMALE)),
        male=Count("id", filter=Q(gender=Gender.MALE)),
        guardian=Count("id", filter=Q(filled_by=FilledBy.GUARDIAN)),
        photo=Count("id", filter=Q(photo_consent=True)),
        opt_in=Count("id", filter=Q(updates_opt_in=True)),
        heard=Count("id", filter=~Q(heard_from="")),
    )
    days = (end - start).days + 1
    s["per_day"] = s["total"] / days
    s["peak_day"], s["peak"] = daily_peak(qs, start, end)
    for k in ("female", "male", "guardian", "photo", "opt_in"):
        s[f"{k}_pct"] = 100 * s[k] / s["total"] if s["total"] else 0
    return s


def change(cur, prev, points=False):
    """How a figure moved against the compare period: {"text", "dir"} (dir: up, down, flat or new).
    `points` compares percentages in percentage points instead of as a relative change."""
    if prev is None:
        return None
    if points:
        diff = cur - prev
        if abs(diff) < 0.05:
            return {"text": "±0 pts", "dir": "flat"}
        return {"text": f"{diff:+.1f} pts", "dir": "up" if diff > 0 else "down"}
    if prev == 0:
        return {"text": "new", "dir": "new"} if cur else {"text": "±0%", "dir": "flat"}
    pct = round(100 * (cur - prev) / prev)
    return {"text": f"{pct:+d}%" if pct else "±0%", "dir": "up" if pct > 0 else "down" if pct < 0 else "flat"}


KPI_TILES = [  # (key, label, kind): kind "count" shows the number, "pct" a share of the period's registrations
    ("total", "registrations", "count"),
    ("per_day", "a day on average", "avg"),
    ("female_pct", "girls", "pct"),
    ("male_pct", "boys", "pct"),
    ("guardian_pct", "filled in by a guardian", "pct"),
    ("photo_pct", "allow photos at events", "pct"),
    ("opt_in_pct", "opted in to updates", "pct"),
]


FORMATS = {"count": "{:,}".format, "avg": "{:,.1f}".format, "pct": "{:.0f}%".format}


def _hour_note(when, hours):
    """The busiest hour's text: just "14:00–15:00" when the range is one day, with the date otherwise."""
    text = bucket_label(when, "hour")
    one_day = hours[0][0].date() == hours[-1][0].date()
    return text.split(", ", 1)[1] if one_day else text


def kpi_tiles(cur, prev, hours=None, prev_hours=None):
    """The headline tiles. With an hourly timeline (`hours`/`prev_hours`: hourly series) the average
    is per hour and the peak is the busiest hour instead of the best day."""
    if hours is not None:
        for k, series in ((cur, hours), (prev, prev_hours)):
            if k is not None:
                k["per_hour"] = k["total"] / max(len(series or []), 1)
                k["peak_hour"], k["peak_hour_n"] = busiest(series or [])
    tiles = []
    for key, label, kind in KPI_TILES:
        if key == "per_day" and hours is not None:
            key, label = "per_hour", "an hour on average"
        value, before = cur[key], prev[key] if prev else None
        fmt = FORMATS[kind]
        tiles.append({"label": label, "value": fmt(value), "prev": fmt(before) if prev else "",
                      "change": change(value, before, points=kind == "pct") if prev else None})
    if hours is not None:
        when = cur["peak_hour"]
        peak = {"label": "busiest hour", "value": f"{cur['peak_hour_n']:,}",
                "note": _hour_note(when, hours) if when else "no registrations"}
        if prev:
            peak.update(prev=f"{prev['peak_hour_n']:,}", change=change(cur["peak_hour_n"], prev["peak_hour_n"]))
    else:
        peak = {"label": "best day", "value": f"{cur['peak']:,}",
                "note": f"{cur['peak_day'].day} {cur['peak_day']:%b %Y}" if cur["peak_day"] else "no registrations"}
        if prev:
            peak.update(prev=f"{prev['peak']:,}", change=change(cur["peak"], prev["peak"]))
    tiles.insert(2, peak)
    return tiles


# ---- Breakdowns ------------------------------------------------------------------------------ #
def counts_by(qs, expr):
    """{value: count} grouped by a field name or an expression."""
    if isinstance(expr, str):
        rows = qs.values_list(expr).annotate(n=Count("id"))
    else:
        rows = qs.annotate(k=expr).values_list("k").annotate(n=Count("id"))
    return dict(rows)


def rows(labels, cur, prev=None, *, sort=True, keep_empty=True, limit=None, link=None):
    """Table rows for a breakdown. labels: [(key, label)]; cur/prev: {key: count}.
    Each row: label, n, share of the period's total, bar width (vs the largest bar of either period),
    and with a compare period its count, share, bar and change. `link(key)` gives the student-list
    query for the row (or None)."""
    total, prev_total = sum(cur.values()), sum(prev.values()) if prev is not None else 0
    if not total and not prev_total:
        return []
    out = []
    for key, label in labels:
        n, before = cur.get(key, 0), prev.get(key, 0) if prev is not None else None
        if not keep_empty and not n and not before:
            continue
        out.append({"key": key, "label": label, "n": n, "share": 100 * n / total if total else 0,
                    "prev": before, "prev_share": 100 * before / prev_total if prev_total else 0,
                    "change": change(n, before), "link": link(key) if link else None})
    if sort:
        out.sort(key=lambda r: (-r["n"], -(r["prev"] or 0)))
    if limit:
        out = out[:limit]
    peak = max([r["n"] for r in out] + [r["prev"] or 0 for r in out] + [1])
    for r in out:
        r["bar"] = round(100 * r["n"] / peak)
        r["prev_bar"] = round(100 * (r["prev"] or 0) / peak)
    return out


NO_REGION = "none"


def region_counts(qs):
    alive = set(Region.objects.values_list("pk", flat=True))
    out = {}
    for k, n in counts_by(qs, "district__region_id").items():
        k = k if k in alive else NO_REGION
        out[k] = out.get(k, 0) + n
    return out


def other_relation_counts(qs):
    return counts_by(qs.filter(guardian_relation=GuardianRelation.OTHER), Lower(Trim("guardian_relation_other")))


def breakdowns(p, cur_qs, prev_qs, link):
    """Every breakdown card on the page, for the period (and the compare period when there is one)."""
    def both(fn):
        return fn(cur_qs), fn(prev_qs) if prev_qs is not None else None

    out = {}

    def simple(name, field_name, labels, param=None, row_link=None, **kw):
        cur, prev = both(lambda qs: counts_by(qs, field_name))
        if param:
            row_link = lambda k: link(**{param: k})  # noqa: E731
        out[name] = rows(labels, cur, prev, link=row_link, **kw)

    simple("gender", "gender", Gender.choices, "gender")
    simple("classes", "current_class", CLASS_CHOICES, "class", sort=False)
    simple("relation", "guardian_relation", GuardianRelation.choices)
    simple("filled_by", "filled_by", FilledBy.choices, "filled_by")
    simple("photo", "photo_consent", [(True, "Allowed"), (False, "Not allowed")], sort=False,
           row_link=lambda k: link(photo="1") if k else None)
    simple("opt_in", "updates_opt_in", [(True, "Opted in"), (False, "Not opted in")], sort=False,
           row_link=lambda k: link(opt_in="1") if k else None)
    simple("heard_from", "heard_from", HeardFrom.choices)

    cur, prev = both(other_relation_counts)
    labels = [(k, k.capitalize() or "(blank)") for k in dict.fromkeys([*cur, *(prev or {})])]
    out["other_relations"] = rows(labels, cur, prev, keep_empty=False, limit=TOP_OTHER_RELATIONS,
                                  link=lambda k: link(adv=typed_relation_query(k)) if k else None)

    cur, prev = both(region_counts)
    labels = [(r.pk, r.name) for r in Region.objects.all()] + [(NO_REGION, "No region")]
    out["regions"] = rows(labels, cur, prev, keep_empty=False,
                          link=lambda k: link(region=k) if k != NO_REGION else None)

    cur, prev = both(lambda qs: counts_by(qs, "district_id"))
    names = District.all_objects.in_bulk([*cur, *(prev or {})])
    labels = [(k, names[k].name) for k in names]
    out["districts"] = rows(labels, cur, prev, keep_empty=False, limit=TOP_DISTRICTS,
                            link=lambda k: link(district=k))

    out["thanas"] = None
    if len(p.districts) == 1:
        cur, prev = both(lambda qs: counts_by(qs, "thana_id"))
        thanas = Thana.all_objects.in_bulk([*cur, *(prev or {})])
        labels = [(k, t.name) for k, t in thanas.items()]
        out["thanas"] = rows(labels, cur, prev, keep_empty=False,
                             link=lambda k: link(thana=k))

    cur, prev = both(lambda qs: counts_by(qs, ExtractIsoWeekDay("created_at", tzinfo=DHAKA)))
    out["weekdays"] = rows(list(enumerate(WEEKDAYS, start=1)), cur, prev, sort=False)

    cur, prev = both(lambda qs: counts_by(qs, ExtractHour("created_at", tzinfo=DHAKA)))
    out["hours"] = rows([(h, f"{h:02d}:00") for h in range(24)], cur, prev, sort=False)
    return out


def typed_relation_query(text):
    """Advanced-search JSON for students whose typed "other" relation is `text` (any case)."""
    cond = {"field": "guardian_relation_other", "op": "eq", "value": text}
    return json.dumps({"match": "all", "groups": [{"match": "all", "conditions": [cond]}]},
                      separators=(",", ":"), ensure_ascii=False)


# ---- Links into the student list --------------------------------------------------------------- #
def student_link_maker(p):
    """A function giving the student list's query string for the period and filters plus extra params."""
    base = {"region": p.regions, "district": p.districts, "class": p.classes,
            "from": p.start.strftime(DATE_FORMAT), "to": p.end.strftime(DATE_FORMAT)}

    def link(**extra):
        params = dict(base)
        for k, v in extra.items():
            params[k] = [str(v)] if k in ("region", "district", "class") else str(v)
        return urlencode(params, doseq=True)
    return link
