"""Advanced (conditional) search for the Students and Schools lists.

A query is JSON: {"match": "all"|"any", "groups": [{"match": "all"|"any", "conditions":
[{"field": key, "op": op, "value": ...}]}]}. Each group matches ALL or ANY of its conditions, and the
groups are combined with ALL or ANY. Only the fields and operators registered below can be used;
values are checked and converted by type, and the query becomes Django ORM filters (no SQL is ever
built from the text). `parse()` returns the filter plus a list of problems: a condition that isn't
valid is dropped and reported, never run.
"""
import json
from contextlib import contextmanager
from dataclasses import dataclass, field as dc_field

from django.db import connection, transaction
from django.db.models import Exists, OuterRef, Q

from apps.core.utils import DATE_FORMAT, parse_date
from apps.reference.models import District, Region, School, SchoolAlias, Thana
from apps.registration.choices import CLASS_CHOICES, FilledBy, Gender, GuardianRelation, HeardFrom
from apps.registration.models import Student

MAX_GROUPS, MAX_CONDITIONS, MAX_TEXT, MAX_LIST = 10, 20, 200, 500
TIME_LIMIT_MS = 5000

# Operators by field type: key -> (label, what value it takes: none | one | two | list)
OPS = {
    "text": {"eq": ("is", "one"), "ne": ("is not", "one"), "contains": ("contains", "one"),
             "not_contains": ("doesn't contain", "one"), "starts": ("starts with", "one"),
             "empty": ("is empty", "none"), "not_empty": ("is not empty", "none")},
    "choice": {"in": ("is any of", "list"), "not_in": ("is none of", "list")},
    "fk": {"in": ("is any of", "list"), "not_in": ("is none of", "list")},
    "number": {"eq": ("=", "one"), "ne": ("≠", "one"), "lt": ("<", "one"), "le": ("≤", "one"), "gt": (">", "one"),
               "ge": ("≥", "one"), "between": ("between", "two")},
    "date": {"eq": ("on", "one"), "lt": ("before", "one"), "le": ("on or before", "one"), "gt": ("after", "one"),
             "ge": ("on or after", "one"), "between": ("between", "two")},
    "bool": {"yes": ("is yes", "none"), "no": ("is no", "none")},
}


@dataclass
class Field:
    key: str
    label: str
    type: str
    path: str = ""
    choices: object = None   # [(value, label)] or a callable returning them (FK fields: id, name)
    group: str = ""          # heading in the field picker
    q: object = None         # custom (op, value) -> Q, for fields that aren't a plain lookup
    ops: list = dc_field(default=None)

    def choice_list(self):
        c = self.choices() if callable(self.choices) else (self.choices or [])
        return [(str(v), str(label)) for v, label in c]

    def allowed_ops(self):
        return {k: v for k, v in OPS[self.type].items() if self.ops is None or k in self.ops}


def _districts():
    return District.objects.order_by("name").values_list("pk", "name")


def _regions():
    return Region.objects.order_by("sort_order", "name").values_list("pk", "name")


THANA_TYPES = [("", "Thana"), (Thana.CANTONMENT, "Cantonment"), (Thana.OTHER, "Other thana (not listed)")]
SCHOOL_STATUS = [(v, label) for v, label in School.Status.choices]


def _school_fields(prefix, group):
    """The government data of a school, reached from `prefix` ("" on schools, "school__" on students)."""
    return [
        Field(f"{prefix}eiin", "EIIN", "text", f"{prefix}eiin", group=group),
        Field(f"{prefix}management", "Management", "choice", f"{prefix}management", School.Management.choices, group),
        Field(f"{prefix}education_level", "Education level", "choice", f"{prefix}education_level",
              School.EducationLevel.choices, group),
        Field(f"{prefix}mpo", "MPO", "choice", f"{prefix}mpo", School.Mpo.choices, group),
        Field(f"{prefix}institute_for", "Institute for", "choice", f"{prefix}institute_for",
              School.InstituteFor.choices, group),
        Field(f"{prefix}area_status", "Area status", "choice", f"{prefix}area_status", School.AreaStatus.choices, group),
        Field(f"{prefix}geographical_position", "Geographical position", "choice", f"{prefix}geographical_position",
              School.GeographicalPosition.choices, group),
    ]


def _alias_q(op, value):
    match = SchoolAlias.objects.filter(school=OuterRef("pk"), alias_text__icontains=value)
    return Q(Exists(match)) if op == "contains" else ~Q(Exists(match))


FIELDS = {
    "students": [
        Field("wikischolar_id", "WikiScholar ID", "text", "wikischolar_id", group="Student"),
        Field("student_name", "Student name", "text", "student_name", group="Student"),
        Field("gender", "Gender", "choice", "gender", Gender.choices, "Student"),
        Field("current_class", "Class", "choice", "current_class", CLASS_CHOICES, "Student"),
        Field("section", "Section", "text", "section", group="Student"),
        Field("class_roll", "Class roll", "text", "class_roll", group="Student"),
        Field("student_id_sid", "Student ID (SID)", "text", "student_id_sid", group="Student"),
        Field("guardian_name", "Guardian name", "text", "guardian_name", group="Guardian & contact"),
        Field("guardian_relation", "Guardian relation", "choice", "guardian_relation", GuardianRelation.choices,
              "Guardian & contact"),
        Field("filled_by", "Form filled in by", "choice", "filled_by", FilledBy.choices, "Guardian & contact"),
        Field("phone", "Phone", "text", "phone", group="Guardian & contact"),
        Field("email", "Email", "text", "email", group="Guardian & contact"),
        Field("updates_opt_in", "Opted in to email updates", "bool", "updates_opt_in", group="Guardian & contact"),
        Field("photo_consent", "Photos allowed at offline events", "bool", "photo_consent", group="Guardian & contact"),
        Field("heard_from", "Heard about WikiScholar from", "choice", "heard_from", HeardFrom.choices,
              "Guardian & contact"),
        Field("created_at", "Registered on", "date", "created_at", group="Guardian & contact"),
        Field("region", "Region", "fk", "district__region_id", _regions, "Place"),
        Field("district", "District", "fk", "district_id", _districts, "Place"),
        Field("thana", "Thana", "text", "thana__name", group="Place", ops=["eq", "ne", "contains", "starts"]),
        Field("thana_type", "Thana type", "choice", "thana__group", THANA_TYPES, "Place"),
        Field("school", "School name", "text", "school__name", group="School",
              ops=["eq", "ne", "contains", "not_contains", "starts"]),
        Field("school_name_as_entered", "School name as typed", "text", "school_name_as_entered", group="School",
              ops=["eq", "ne", "contains", "not_contains", "starts"]),
        Field("school_status", "School status", "choice", "school__verification_status", SCHOOL_STATUS, "School"),
        Field("school_resolution", "How the school was matched", "choice", "school_resolution",
              Student.SchoolResolution.choices, "School"),
        *_school_fields("school__", "School (government data)"),
    ],
    "schools": [
        Field("name", "Name", "text", "name", group="School"),
        Field("alias", "Alias (other spelling)", "text", q=_alias_q, group="School", ops=["contains", "not_contains"]),
        Field("status", "Status", "choice", "verification_status", SCHOOL_STATUS, "School"),
        Field("source", "Added by", "choice", "source", School.Source.choices, "School"),
        Field("students", "Number of students", "number", "n", group="School"),
        Field("created_at", "Added on", "date", "created_at", group="School"),
        Field("region", "Region", "fk", "district__region_id", _regions, "Place"),
        Field("district", "District", "fk", "district_id", _districts, "Place"),
        Field("division", "Division", "text", "division", group="Place", ops=["eq", "ne", "contains", "empty", "not_empty"]),
        Field("thana", "Thana", "text", "thana__name", group="Place"),
        Field("post_office", "Post office", "text", "post_office", group="Place"),
        *_school_fields("", "Government data"),
        Field("email", "Email", "text", "email", group="Government data"),
    ],
}
BY_KEY = {entity: {f.key: f for f in fields} for entity, fields in FIELDS.items()}


def _condition_q(f, op, value):
    if f.q:
        return f.q(op, value)
    p = f.path
    if f.type == "text":
        return {"eq": lambda: Q(**{f"{p}__iexact": value}), "ne": lambda: ~Q(**{f"{p}__iexact": value}),
                "contains": lambda: Q(**{f"{p}__icontains": value}),
                "not_contains": lambda: ~Q(**{f"{p}__icontains": value}),
                "starts": lambda: Q(**{f"{p}__istartswith": value}),
                "empty": lambda: Q(**{p: ""}) | Q(**{f"{p}__isnull": True}),
                "not_empty": lambda: ~Q(**{p: ""}) & Q(**{f"{p}__isnull": False})}[op]()
    if f.type in ("choice", "fk"):
        return Q(**{f"{p}__in": value}) if op == "in" else ~Q(**{f"{p}__in": value})
    if f.type == "bool":
        return Q(**{p: op == "yes"})
    if f.type == "date":
        p = f"{p}__date"
    if op == "between":
        return Q(**{f"{p}__gte": value[0], f"{p}__lte": value[1]})
    lookup = {"eq": "", "lt": "__lt", "le": "__lte", "gt": "__gt", "ge": "__gte"}.get(op)
    return ~Q(**{p: value}) if op == "ne" else Q(**{f"{p}{lookup}": value})


def _clean_value(f, takes, value):
    """The value converted for the ORM, or raises ValueError with a message."""
    if takes == "none":
        return None
    if f.type == "text":
        value = str(value if value is not None else "").strip()
        if not value:
            raise ValueError("needs a value")
        if len(value) > MAX_TEXT:
            raise ValueError(f"is longer than {MAX_TEXT} characters")
        return value
    if f.type in ("choice", "fk"):
        values = [str(v) for v in (value if isinstance(value, list) else [value]) if v is not None]
        allowed = {v for v, _ in f.choice_list()}
        if not values:
            raise ValueError("needs at least one choice")
        if len(values) > MAX_LIST:
            raise ValueError(f"has more than {MAX_LIST} choices")
        bad = [v for v in values if v not in allowed]
        if bad:
            raise ValueError(f"has an unknown choice ({', '.join(bad[:3])})")
        return [int(v) for v in values] if f.type == "fk" else values
    if f.type in ("number", "date"):
        parts = value if takes == "two" else [value]
        if not isinstance(parts, list) or len(parts) != (2 if takes == "two" else 1):
            raise ValueError("needs two values" if takes == "two" else "needs a value")
        out = []
        for v in parts:
            if f.type == "number":
                try:
                    out.append(int(str(v).strip()))
                except (TypeError, ValueError):
                    raise ValueError("needs a whole number") from None
            else:
                d = parse_date(str(v or ""))
                if not d:
                    raise ValueError("needs a date (dd/mm/yyyy)")
                out.append(d)
        return out if takes == "two" else out[0]
    raise ValueError("can't be used")


def load(raw):
    """JSON text (or a dict) -> dict; {} for anything that isn't a query object."""
    if isinstance(raw, dict):
        return raw
    try:
        data = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def parse(entity, raw):
    """(Q, problems, cleaned query). The cleaned query keeps only valid conditions, with values as
    given (dates stay dd/mm/yyyy), so it can be stored, shown and edited again."""
    data, fields, problems = load(raw), BY_KEY[entity], []
    match = "any" if data.get("match") == "any" else "all"
    groups = data.get("groups") if isinstance(data.get("groups"), list) else []
    if len(groups) > MAX_GROUPS:
        problems.append(f"Only the first {MAX_GROUPS} groups are used.")
        groups = groups[:MAX_GROUPS]
    group_qs, cleaned_groups = [], []
    for gi, g in enumerate(groups, start=1):
        if not isinstance(g, dict):
            continue
        conditions = g.get("conditions") if isinstance(g.get("conditions"), list) else []
        if len(conditions) > MAX_CONDITIONS:
            problems.append(f"Group {gi}: only the first {MAX_CONDITIONS} conditions are used.")
            conditions = conditions[:MAX_CONDITIONS]
        g_match = "any" if g.get("match") == "any" else "all"
        qs, kept = [], []
        for c in conditions:
            if not isinstance(c, dict):
                continue
            f = fields.get(c.get("field"))
            if f is None:
                problems.append(f"Group {gi}: “{c.get('field')}” can't be searched (any more), so it was left out.")
                continue
            ops = f.allowed_ops()
            if c.get("op") not in ops:
                problems.append(f"Group {gi}: {f.label} can't use “{c.get('op')}”, so it was left out.")
                continue
            takes = ops[c["op"]][1]
            try:
                value = _clean_value(f, takes, c.get("value"))
            except ValueError as exc:
                problems.append(f"Group {gi}: {f.label} {exc}, so it was left out.")
                continue
            qs.append(_condition_q(f, c["op"], value))
            kept.append({"field": f.key, "op": c["op"], **({} if takes == "none" else {"value": c.get("value")})})
        if qs:
            group_qs.append(_combine(qs, g_match))
            cleaned_groups.append({"match": g_match, "conditions": kept})
    cleaned = {"match": match, "groups": cleaned_groups} if cleaned_groups else {}
    return (_combine(group_qs, match) if group_qs else Q()), problems, cleaned


def _combine(qs, match):
    out = qs[0]
    for q in qs[1:]:
        out = (out | q) if match == "any" else (out & q)
    return out


def normalize(entity, raw):
    """Compact JSON of the valid part of the query, or "" (for URLs and saved filters)."""
    cleaned = parse(entity, raw)[2]
    return json.dumps(cleaned, separators=(",", ":"), ensure_ascii=False) if cleaned else ""


def _value_text(f, takes, value):
    if takes == "none":
        return ""
    if f.type in ("choice", "fk"):
        labels = dict(f.choice_list())
        values = value if isinstance(value, list) else [value]
        return ", ".join(labels.get(str(v), str(v)) for v in values)
    if takes == "two":
        return f"{value[0]} and {value[1]}"
    return f"“{value}”" if f.type == "text" else str(value)


def describe(entity, raw):
    """Plain English, e.g. "District is any of Dhaka, Gazipur AND Class is any of 8, 9"."""
    cleaned, fields = parse(entity, raw)[2], BY_KEY[entity]
    parts = []
    for g in cleaned.get("groups", []):
        conds = []
        for c in g["conditions"]:
            f = fields[c["field"]]
            label, takes = f.allowed_ops()[c["op"]]
            conds.append(" ".join(x for x in (f.label, label, _value_text(f, takes, c.get("value"))) if x))
        text = (" OR " if g["match"] == "any" else " AND ").join(conds)
        parts.append(f"({text})" if len(conds) > 1 and len(cleaned["groups"]) > 1 else text)
    return (" OR " if cleaned.get("match") == "any" else " AND ").join(parts)


def metadata(entity):
    """Fields, operators and choices for the query builder on the page (json_script)."""
    return {"fields": [{"key": f.key, "label": f.label, "type": f.type, "group": f.group,
                        "ops": [{"key": k, "label": label, "takes": takes} for k, (label, takes) in f.allowed_ops().items()],
                        "choices": f.choice_list() if f.type in ("choice", "fk") else []}
                       for f in FIELDS[entity]],
            "date_format": DATE_FORMAT}


@contextmanager
def time_limit(active=True):
    """Stop a slow advanced search instead of letting it tie up the database (roadmap 5.2)."""
    if not active:
        yield
        return
    with transaction.atomic():
        with connection.cursor() as cur:
            cur.execute("SET LOCAL statement_timeout = %s", [TIME_LIMIT_MS])
        yield
