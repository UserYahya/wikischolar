import re

from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.core.utils import english_text, to_en_digits  # noqa: F401 (english_text is re-exported for forms)

from .models import PHONE_REGEX

_PHONE = re.compile(PHONE_REGEX)


def normalize_phone(raw):
    """Accepts +8801XXXXXXXXX, 8801..., 01..., Bangla digits, spaces and dashes."""
    digits = re.sub(r"[^\d]", "", to_en_digits(raw or ""))
    if digits.startswith("880"):
        digits = digits[2:]
    elif digits.startswith("88") and len(digits) == 13:
        digits = digits[2:]
    return digits


def validate_phone(value):
    if not _PHONE.match(value or ""):
        raise ValidationError("Enter a valid Bangladeshi mobile number (for example 01712345678).", code="phone")


def validate_past_date(value):
    today = timezone.localdate()
    if value >= today:
        raise ValidationError("Date of birth must be in the past.", code="dob_future")
    if value.year < today.year - 30:
        raise ValidationError("Please check the date of birth.", code="dob_too_old")


# ---- Email typo detection (warning, never a block) ------------------------ #
POPULAR_DOMAINS = ["gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "live.com",
                   "icloud.com", "ymail.com", "yahoo.co.uk", "protonmail.com", "googlemail.com"]
KNOWN_TYPOS = {
    "gamil.com": "gmail.com", "gnail.com": "gmail.com", "gmial.com": "gmail.com", "gmai.com": "gmail.com",
    "gmail.co": "gmail.com", "gmail.con": "gmail.com", "gmail.cm": "gmail.com", "gmaill.com": "gmail.com",
    "hotmial.com": "hotmail.com", "hotmai.com": "hotmail.com", "hotmil.com": "hotmail.com",
    "yaho.com": "yahoo.com", "yahooo.com": "yahoo.com", "yahoo.con": "yahoo.com",
    "outlok.com": "outlook.com", "outllook.com": "outlook.com",
}
LEGIT_LOOKALIKES = {"mail.com", "gmx.com", "email.com", "yandex.com", "aol.com", "zoho.com"}


def _levenshtein(a, b):
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def suggest_email_domain(email):
    """Return a corrected domain if the entered one looks like a typo, else None.
    Also catches a missing or mistyped dot ("gmailcom", "gmail", "gmail,com")."""
    if "@" not in (email or ""):
        return None
    domain = email.rsplit("@", 1)[1].lower().strip().strip(".")
    if not domain or domain in POPULAR_DOMAINS or domain in LEGIT_LOOKALIKES:
        return None
    fixed = re.sub(r"[,;: ]+", ".", domain)
    if fixed in POPULAR_DOMAINS:
        return fixed
    if fixed in KNOWN_TYPOS:
        return KNOWN_TYPOS[fixed]
    if "." not in fixed:
        # "gmail" / "gmailcom" / "gmial": compare with each popular name with and without its dot
        for d in POPULAR_DOMAINS:
            if fixed in (d.split(".")[0], d.replace(".", "")):
                return d
        best = min(POPULAR_DOMAINS, key=lambda d: _levenshtein(fixed, d.replace(".", "")))
        return best if _levenshtein(fixed, best.replace(".", "")) <= 2 else None
    best = min(POPULAR_DOMAINS, key=lambda d: _levenshtein(fixed, d))
    return best if _levenshtein(fixed, best) <= 2 else None
