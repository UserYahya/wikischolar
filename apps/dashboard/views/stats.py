from functools import partial

from django.shortcuts import render
from django.utils import timezone

from apps.core.permissions import require_perm
from apps.dashboard import charts, stats
from apps.reference.models import District, Region
from apps.registration.choices import CLASS_CHOICES


def _range_text(start, end):
    if start == end:
        return f"{start.day} {start:%b %Y}"
    first = f"{start.day} {start:%b}" + ("" if start.year == end.year else f" {start:%Y}")
    return f"{first} – {end.day} {end:%b %Y}"


@require_perm("stats.view")
def stats_page(request):
    """Registration statistics for any date range, optionally compared with another period, and
    narrowed by region, district and class. Counts only, so an Organiser can use it too; links into
    the student list are shown only to roles that can open it."""
    today = timezone.localdate()
    p = stats.resolve(request.GET, today, stats.first_registration_day())
    base = stats.filtered(p)
    cur_qs = stats.in_period(base, p.start, p.end)
    prev_qs = stats.in_period(base, p.cmp_start, p.cmp_end) if p.comparing else None

    cur_k = stats.kpis(base, p.start, p.end)
    prev_k = stats.kpis(base, p.cmp_start, p.cmp_end) if p.comparing else None

    series = stats.timeseries(base, p.start, p.end, p.by)
    prev_series = stats.timeseries(base, p.cmp_start, p.cmp_end, p.by) if p.comparing else None
    if prev_series and p.cmp in ("prev", "year"):
        # Same length as the period, but the weeks/months can fall differently and leave the compare
        # period one extra, nearly empty bucket at the end; drop it so the lines end together.
        prev_series = prev_series[:len(series)]
    label = partial(stats.bucket_label, by=p.by)
    short = partial(stats.bucket_label, by=p.by, short=True)

    can_students = request.user.has_perm_code("students.view")
    link = stats.student_link_maker(p) if can_students else (lambda **kw: None)
    b = stats.breakdowns(p, cur_qs, prev_qs, link)

    over_time = []
    for i in range(max(len(series), len(prev_series or []))):
        row = {"label": label(series[i][0]) if i < len(series) else "", "n": series[i][1] if i < len(series) else None}
        if prev_series is not None:
            before = prev_series[i] if i < len(prev_series) else None
            row.update(prev_label=label(before[0]) if before else "", prev=before[1] if before else None,
                       change=stats.change(row["n"] or 0, before[1]) if before and row["n"] is not None else None)
        over_time.append(row)

    query = request.GET.copy()
    group_links = []
    for key, text in stats.GROUPINGS.items():
        query["by"] = key
        group_links.append({"key": key, "text": text, "qs": query.urlencode(), "on": key == p.by_choice})

    return render(request, "dashboard/stats.html", {
        "p": p, "ranges": stats.RANGES, "compares": stats.COMPARES,
        "range_text": _range_text(p.start, p.end),
        "cmp_text": _range_text(p.cmp_start, p.cmp_end) if p.comparing else "",
        "from_value": request.GET.get("from", "") if p.range == "custom" else p.start.strftime("%d/%m/%Y"),
        "to_value": request.GET.get("to", "") if p.range == "custom" else p.end.strftime("%d/%m/%Y"),
        "cmp_from_value": p.cmp_start.strftime("%d/%m/%Y") if p.comparing else request.GET.get("cmp_from", ""),
        "cmp_to_value": p.cmp_end.strftime("%d/%m/%Y") if p.comparing else request.GET.get("cmp_to", ""),
        "regions": Region.objects.prefetch_related("districts"),
        "unassigned_districts": District.objects.filter(region__isnull=True),
        "open_regions": {str(r) for r in District.objects.filter(pk__in=p.districts).values_list("region_id", flat=True)},
        "classes": CLASS_CHOICES,
        "filter_count": len(p.regions) + len(p.districts) + len(p.classes),
        "tiles": stats.kpi_tiles(cur_k, prev_k),
        "total": cur_k["total"], "prev_total": prev_k["total"] if prev_k else None,
        "heard": cur_k["heard"],
        "line": charts.line_chart(series, prev_series, label, short),
        "over_time": over_time, "group_links": group_links,
        "b": b, "hours_chart": charts.column_chart(b["hours"], xlabel_every=3),
        "students_link": link(), "can_students": can_students,
    })
