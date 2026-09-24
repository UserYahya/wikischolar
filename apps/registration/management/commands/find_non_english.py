from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand

from apps.core.utils import english_text
from apps.reference.models import School, SchoolAlias
from apps.registration.models import Student

STUDENT_FIELDS = ["student_name", "guardian_name", "guardian_relation_other", "school_name_as_entered",
                  "class_roll", "student_id_sid"]


def _bad(value):
    """Not English, or English only after cleaning (e.g. Bangla digits)."""
    try:
        return english_text(value) != (value or "")
    except ValidationError:
        return True


class Command(BaseCommand):
    help = ("List stored values that aren't English (registered before the English-only rule). "
            "Fix them from the dashboard: student Edit, or Schools -> Rename.")

    def handle(self, *args, **opts):
        found = 0
        for s in Student.all_objects.only("wikischolar_id", *STUDENT_FIELDS).iterator():
            for f in STUDENT_FIELDS:
                if _bad(getattr(s, f)):
                    found += 1
                    self.stdout.write(f"student {s.wikischolar_id}  {f}: {getattr(s, f)}")
        for sc in School.objects.only("pk", "name").iterator():
            if _bad(sc.name):
                found += 1
                self.stdout.write(f"school #{sc.pk}  name: {sc.name}")
        for a in SchoolAlias.objects.only("pk", "school_id", "alias_text").iterator():
            if _bad(a.alias_text):
                found += 1
                self.stdout.write(f"alias #{a.pk} (school #{a.school_id}): {a.alias_text}")
        self.stdout.write(self.style.SUCCESS("All stored text is English.") if not found
                          else self.style.WARNING(f"{found} non-English value(s) found."))
