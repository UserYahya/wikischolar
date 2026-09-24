"""Public JSON endpoints used by the registration form (and the dashboard editor)."""
from django.http import JsonResponse
from django.views.decorators.http import require_GET

from apps.core import ratelimit
from apps.core.utils import client_ip

from . import services
from .models import District, Upazila


def _limited(request):
    return not ratelimit.allow("api_per_ip", client_ip(request) or "unknown")


@require_GET
def districts(request):
    if _limited(request):
        return JsonResponse({"error": "rate_limited"}, status=429)
    data = []
    for d in services.districts_with_regions():
        region = services.region_for_district(d)
        data.append({
            "id": d.pk, "name": d.name, "name_bn": d.name_bn,
            "region": {"id": region.pk, "name": region.name, "name_bn": region.name_bn} if region else None,
        })
    return JsonResponse({"districts": data})


@require_GET
def upazilas(request, district_id):
    if _limited(request):
        return JsonResponse({"error": "rate_limited"}, status=429)
    if not District.objects.filter(pk=district_id).exists():
        return JsonResponse({"error": "not_found"}, status=404)
    rows = Upazila.objects.filter(district_id=district_id).order_by("name")
    return JsonResponse({"upazilas": [{"id": u.pk, "name": u.name, "name_bn": u.name_bn} for u in rows]})


@require_GET
def schools(request):
    if _limited(request):
        return JsonResponse({"error": "rate_limited"}, status=429)
    try:
        upazila_id = int(request.GET.get("upazila", ""))
    except ValueError:
        return JsonResponse({"error": "upazila_required"}, status=400)
    q = request.GET.get("q", "")[:120]
    # Dashboard editor (signed-in staff, ?all=1): every school incl. pending. Public form: approved only.
    staff_list = bool(request.GET.get("all")) and request.user.is_authenticated
    results = services.search_schools(upazila_id, q, limit=500 if staff_list else 8, verified_only=not staff_list)
    return JsonResponse({"schools": [
        {"id": s.pk, "name": s.name, "verified": s.verification_status == "verified"} for s in results
    ]})
