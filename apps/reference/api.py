"""Public JSON endpoints used by the registration form (and the dashboard editor)."""
from django.http import JsonResponse
from django.views.decorators.http import require_GET

from apps.core import ratelimit
from apps.core.utils import client_ip

from . import services
from .models import District


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
    # Upazilas and the other areas (city-corporation thanas, cantonments, "Other area"), in list
    # order; "group" / "group_bn" are the dropdown headings.
    return JsonResponse({"upazilas": [
        {"id": u.pk, "name": u.name, "name_bn": u.name_bn, "group": u.group_label, "group_bn": u.group_label_bn}
        for u in services.areas_of(district_id)]})


@require_GET
def schools(request):
    if _limited(request):
        return JsonResponse({"error": "rate_limited"}, status=429)
    # ?district=&upazila= : the whole district, the student's own area (upazila) first (public form,
    # dashboard Add school). ?upazila= alone: one area only (dashboard student editor list).
    district_id, upazila_id = _int(request.GET.get("district")), _int(request.GET.get("upazila"))
    if not (district_id or upazila_id):
        return JsonResponse({"error": "district_or_upazila_required"}, status=400)
    q = request.GET.get("q", "")[:120]
    # Signed-in staff also see pending schools: ?all=1 lists every school (student editor),
    # ?pending=1 is the typeahead on the dashboard's Add school page. Public form: approved only.
    staff = request.user.is_authenticated
    staff_list = bool(request.GET.get("all")) and staff
    with_pending = staff_list or (bool(request.GET.get("pending")) and staff)
    if district_id:
        results = services.search_schools(query=q, limit=500 if staff_list else 8, verified_only=not with_pending,
                                          district_id=district_id, prefer_upazila_id=upazila_id)
    else:
        results = services.search_schools(upazila_id, q, limit=500 if staff_list else 8, verified_only=not with_pending)
    return JsonResponse({"schools": [
        {"id": s.pk, "name": s.name, "verified": s.verification_status == "verified",
         # area "" = not known yet (a school listed for the whole district)
         "area": s.upazila.name if s.upazila_id else "", "area_bn": s.upazila.name_bn if s.upazila_id else "",
         "same_area": bool(s.upazila_id) and s.upazila_id == upazila_id}
        for s in results
    ]})


def _int(value):
    try:
        return int(value or "")
    except ValueError:
        return None
