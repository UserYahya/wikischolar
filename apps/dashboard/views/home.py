from datetime import timedelta

from django.db.models import Count, Q
from django.db.models.functions import TruncDate
from django.shortcuts import render
from django.utils import timezone

from apps.core.permissions import require_perm
from apps.notifications import services as notify
from apps.reference.models import District, Region, School, Thana
from apps.registration.choices import HeardFrom
from apps.registration.models import Student


@require_perm("students.view")
def home(request):
    students = Student.objects.all()
    today = timezone.localdate()
    start = today - timedelta(days=13)
    daily = dict(students.filter(created_at__date__gte=start).annotate(d=TruncDate("created_at"))
                 .values_list("d").annotate(n=Count("id")))
    days = [(start + timedelta(days=i), daily.get(start + timedelta(days=i), 0)) for i in range(14)]
    peak = max([n for _, n in days] + [1])
    by_region = list(Region.objects.annotate(n=Count("districts__students", distinct=True, filter=Q(districts__students__is_deleted=False))).order_by("-n", "name"))
    unassigned = students.filter(district__region__isnull=True).count()
    top_districts = (District.objects.annotate(n=Count("students", filter=Q(students__is_deleted=False))).filter(n__gt=0).select_related("region")
                     .order_by("-n")[:10])
    region_peak = max([r.n for r in by_region] + [unassigned, 1])
    heard = dict(students.exclude(heard_from="").values_list("heard_from").annotate(n=Count("id")))
    heard_rows = sorted(((label, heard.get(value, 0)) for value, label in HeardFrom.choices), key=lambda r: -r[1])
    heard_peak = max([n for _, n in heard_rows] + [1])
    return render(request, "dashboard/home.html", {
        "total": students.count(),
        "today": students.filter(created_at__date=today).count(),
        "week": students.filter(created_at__date__gte=today - timedelta(days=6)).count(),
        "pending_schools": School.objects.filter(verification_status="pending").count(),
        "other_area": students.filter(thana__group=Thana.OTHER).count(),
        "unassigned_districts": District.objects.filter(region__isnull=True).count(),
        "days": [(d, n, round(100 * n / peak)) for d, n in days],
        "by_region": [(r, round(100 * r.n / region_peak)) for r in by_region],
        "unassigned": unassigned, "unassigned_pct": round(100 * unassigned / region_peak),
        "top_districts": top_districts,
        "heard_from": [(label, n, round(100 * n / heard_peak)) for label, n in heard_rows],
        "heard_answered": sum(heard.values()),
        "email": notify.email_delivery(),
        "can_set_email": request.user.has_perm_code("settings.manage"),
    })
