import re

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


def client_ip(request):
    if getattr(settings, "TRUST_X_FORWARDED_FOR", False):
        fwd = request.META.get("HTTP_X_FORWARDED_FOR", "")
        if fwd:
            return fwd.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")
