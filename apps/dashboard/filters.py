"""One filter definition shared by the student list, CSV export and bulk messaging."""
from django.db.models import Q

from apps.core.utils import DATE_FORMAT, parse_date
from apps.dashboard import advanced
from apps.notifications import services as notify
from apps.notifications.models import NotificationLog
from apps.reference.models import Thana
from apps.registration.choices import FilledBy
from apps.registration.models import Student

SORTS = {
    "newest": "-created_at", "oldest": "created_at", "name": "student_name", "id": "wikischolar_id",
    "district": "district__name", "school": "school__name", "class": "current_class",
}
MULTI = ("district", "region", "class", "gender")
SINGLE = ("thana", "area_kind", "school", "from", "to", "q", "opt_in", "filled_by", "sort", "batch_size", "batch",
          "msg_batch", "msg_batch_mode", "adv")
# Params that narrow the list (sort and batching only reorder or split it).
NARROWING = MULTI + ("thana", "area_kind", "school", "from", "to", "q", "opt_in", "filled_by", "msg_batch", "adv")
# Thana type filter: what kind of thana the student chose. "other" finds students to move.
AREA_KINDS = {"thana": "Thana", "cantonment": "Cantonment", "other": "Other thana (not listed)"}
# Before thanas replaced "Upazila / Area" (Oct 2026): old links and saved batch filters use these.
OLD_PARAMS = {"upazila": "thana"}
OLD_AREA_KINDS = {"upazila": "thana"}
OLD_AREA_KIND_LABELS = {"city": "City-corporation thana"}
# Message history filter: students a message batch was sent to, not sent to, or not delivered to.
MSG_BATCH_MODES = {"sent": "Received", "not_sent": "Not sent", "not_delivered": "Not delivered"}
MAX_BATCH_SIZE = 100_000


def _date_label(v):
    d = parse_date(v)
    return d.strftime(DATE_FORMAT) if d else v


def _positive_int(v, upper):
    try:
        n = int(str(v).strip())
    except (TypeError, ValueError):
        return None
    return n if 1 <= n <= upper else None


def params_from(querydict):
    p = {k: [v for v in querydict.getlist(k) if v] for k in MULTI}
    p.update({k: querydict.get(k, "").strip() for k in SINGLE})
    for old, new in OLD_PARAMS.items():
        p[new] = p[new] or querydict.get(old, "").strip()
    p["area_kind"] = OLD_AREA_KINDS.get(p["area_kind"], p["area_kind"])
    p["adv"] = advanced.normalize("students", p["adv"])  # only the valid conditions, as compact JSON
    # Show dates as dd/mm/yyyy even when a link carries yyyy-mm-dd.
    p["from"], p["to"] = _date_label(p["from"]), _date_label(p["to"])
    if not p["msg_batch"]:
        p["msg_batch_mode"] = ""
    elif p["msg_batch_mode"] not in MSG_BATCH_MODES:
        p["msg_batch_mode"] = "sent"
    size = _positive_int(p["batch_size"], MAX_BATCH_SIZE)
    p["batch_size"] = str(size) if size else ""
    p["batch"] = str(_positive_int(p["batch"], MAX_BATCH_SIZE) or "") if size else ""
    if size and p["sort"] not in SORTS:
        # Oldest-first keeps existing batches stable as new students register.
        p["sort"] = "oldest"
    return p


def active_count(p):
    return sum(1 for k in NARROWING if p.get(k))


def snapshot(p):
    # Sort only matters when it decides batch membership.
    return {k: v for k, v in p.items() if v and (k != "sort" or p["batch"])}


def apply(p, qs=None):
    qs = (qs if qs is not None else Student.objects.all()).select_related(
        "district__region", "thana", "school")
    if p["district"]:
        qs = qs.filter(district_id__in=p["district"])
    if p["region"]:
        qs = qs.filter(district__region_id__in=p["region"])
    if p["thana"]:
        qs = qs.filter(thana_id=p["thana"])
    if p["school"]:
        qs = qs.filter(school_id=p["school"])
    if p["class"]:
        qs = qs.filter(current_class__in=p["class"])
    if p["gender"]:
        qs = qs.filter(gender__in=p["gender"])
    if parse_date(p["from"]):
        qs = qs.filter(created_at__date__gte=parse_date(p["from"]))
    if parse_date(p["to"]):
        qs = qs.filter(created_at__date__lte=parse_date(p["to"]))
    if p["opt_in"] == "1":
        qs = qs.filter(updates_opt_in=True)
    if p["filled_by"] in FilledBy.values:
        qs = qs.filter(filled_by=p["filled_by"])
    if p["area_kind"] == "thana":
        qs = qs.filter(thana__group="")
    elif p["area_kind"] == "cantonment":
        qs = qs.filter(thana__group=Thana.CANTONMENT)
    elif p["area_kind"] == "other":
        qs = qs.filter(thana__group=Thana.OTHER)
    if p.get("adv"):
        qs = qs.filter(advanced.parse("students", p["adv"])[0])
    if p["msg_batch"]:
        if p["msg_batch_mode"] == "not_sent":
            qs = qs.exclude(pk__in=notify.student_ids_in_batch(p["msg_batch"]))
        else:
            statuses = NotificationLog.NOT_DELIVERED if p["msg_batch_mode"] == "not_delivered" else None
            qs = qs.filter(pk__in=notify.student_ids_in_batch(p["msg_batch"], statuses))
    if p["q"]:
        q = p["q"]
        qs = qs.filter(Q(student_name__icontains=q) | Q(wikischolar_id__iexact=q) | Q(phone__contains=q)
                       | Q(email__icontains=q) | Q(guardian_name__icontains=q) | Q(school__name__icontains=q))
    order = SORTS.get(p["sort"], "-created_at")
    qs = qs.order_by(order, "-id" if order.startswith("-") else "id")  # tiebreak in the same direction
    if p["batch"]:
        size, n = int(p["batch_size"]), int(p["batch"])
        ids = list(qs.values_list("pk", flat=True)[(n - 1) * size:n * size])
        qs = qs.filter(pk__in=ids)  # a filter, not a slice, so callers can keep filtering
    return qs


def batches(p, total):
    """[{number, first, last, count}] splitting `total` filtered students into batches of p["batch_size"]."""
    if not p["batch_size"] or not total:
        return []
    size = int(p["batch_size"])
    return [{"number": i + 1, "first": i * size + 1, "last": min((i + 1) * size, total),
             "count": min(size, total - i * size)} for i in range((total + size - 1) // size)]


def describe(snap):
    """Human-readable [(label, text)] for a stored filter snapshot. Snapshots keep IDs
    (stable across renames); names are resolved at display time."""
    from apps.reference.models import District, Region, School
    from apps.registration.choices import Gender

    def names(model, ids):
        ids = ids if isinstance(ids, (list, tuple)) else [ids]
        found = dict(model.all_objects.filter(pk__in=[i for i in ids if str(i).isdigit()])
                     .values_list("pk", "name")) if hasattr(model, "all_objects") else \
            dict(model.objects.filter(pk__in=[i for i in ids if str(i).isdigit()]).values_list("pk", "name"))
        return ", ".join(found.get(int(i), f"#{i}") if str(i).isdigit() else str(i) for i in ids)

    out = []
    snap = snap or {}
    if snap.get("region"):
        out.append(("Region", names(Region, snap["region"])))
    if snap.get("district"):
        out.append(("District", names(District, snap["district"])))
    if snap.get("thana") or snap.get("upazila"):  # batches saved before the rename say "upazila"
        out.append(("Thana", names(Thana, snap.get("thana") or snap["upazila"])))
    if snap.get("school"):
        out.append(("School", names(School, snap["school"])))
    if snap.get("class"):
        out.append(("Class", ", ".join(map(str, snap["class"]))))
    if snap.get("gender"):
        labels = dict(Gender.choices)
        out.append(("Gender", ", ".join(str(labels.get(g, g)) for g in snap["gender"])))
    if snap.get("from") or snap.get("to"):
        out.append(("Registered", f"{_date_label(snap.get('from') or '') or '…'} to {_date_label(snap.get('to') or '') or '…'}"))
    kind = OLD_AREA_KINDS.get(snap.get("area_kind"), snap.get("area_kind"))
    if kind in AREA_KINDS or kind in OLD_AREA_KIND_LABELS:
        out.append(("Thana type", AREA_KINDS.get(kind) or OLD_AREA_KIND_LABELS[kind]))
    if snap.get("filled_by") in FilledBy.values:
        out.append(("Filled in by", FilledBy(snap["filled_by"]).label))
    if snap.get("opt_in") == "1":
        out.append(("Email updates", "opted in"))
    if snap.get("q"):
        out.append(("Search", f"“{snap['q']}”"))
    if snap.get("adv"):
        out.append(("Advanced search", advanced.describe("students", snap["adv"])))
    if snap.get("msg_batch"):
        batch = notify.get_batch(snap["msg_batch"])
        label = batch.label if batch else snap["msg_batch"]
        mode = MSG_BATCH_MODES.get(snap.get("msg_batch_mode") or "sent", "Received")
        out.append(("Message history", f"{mode}: {label}"))
    if snap.get("batch") and snap.get("batch_size"):
        out.append(("Batch", f"#{snap['batch']} ({snap['batch_size']} per batch, sorted by {snap.get('sort') or 'newest'})"))
    return out
