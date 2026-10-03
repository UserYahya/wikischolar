import re
from datetime import datetime

from django import forms
from django.conf import settings
from django.core.exceptions import ValidationError

BN_DIGITS = str.maketrans("0123456789", "০১২৩৪৫৬৭৮৯")
EN_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")


def to_bn_digits(value):
    return str(value).translate(BN_DIGITS)


def to_en_digits(value):
    return str(value).translate(EN_DIGITS)


# Every free-text value (student, guardian and school names, roll, SID) is stored in
# English so the database holds one script only. Keep static/js/register.js in sync.
_ENGLISH = re.compile(r"^[A-Za-z0-9 .,'()&/\-]*$")
ENGLISH_ONLY_MESSAGE = "Please write this in English (A-Z letters and 0-9 digits only)."


def english_text(raw):
    """Collapse whitespace and turn Bangla digits into 0-9, then insist on English."""
    value = " ".join(to_en_digits(raw or "").split())
    if not _ENGLISH.match(value):
        raise ValidationError(ENGLISH_ONLY_MESSAGE, code="not_english")
    return value


# Dates are typed and shown British style, dd/mm/yyyy. yyyy-mm-dd is still read so older links,
# saved filters and API clients keep working. Keep static/js/datefield.js in sync.
DATE_INPUT_FORMATS = ["%d/%m/%Y", "%Y-%m-%d"]
DATE_FORMAT = "%d/%m/%Y"
DATE_INVALID_MESSAGE = "Enter the date as dd/mm/yyyy, for example 14/03/2012."


def parse_date(raw):
    """dd/mm/yyyy (or yyyy-mm-dd, Bangla digits allowed) → date, or None."""
    value = to_en_digits(raw or "").strip()
    for fmt in DATE_INPUT_FORMATS:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


class BritishDateField(forms.DateField):
    """A DateField that reads dd/mm/yyyy first (see DATE_INPUT_FORMATS) and Bangla digits."""
    input_formats = DATE_INPUT_FORMATS
    default_error_messages = {"invalid": DATE_INVALID_MESSAGE}

    def to_python(self, value):
        return super().to_python(to_en_digits(value).strip() if isinstance(value, str) else value)


def client_ip(request):
    if getattr(settings, "TRUST_X_FORWARDED_FOR", False):
        fwd = request.META.get("HTTP_X_FORWARDED_FOR", "")
        if fwd:
            return fwd.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")
