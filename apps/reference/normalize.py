"""Normalisation used for school-name matching (both at entry and in dedupe)."""
import re
import unicodedata

# Applied in order, on lower-cased text, before punctuation is stripped.
_REWRITES = [
    (r"\bh\s*/\s*s\b", "high school"),
    (r"\bs\s*/\s*c\b", "school and college"),
    (r"\bgovt?\.?(?=\s|$)", "government"),
    (r"\bgov\.?(?=\s|$)", "government"),
    (r"\bsch\.?(?=\s|$)", "school"),
    (r"\bclg\.?(?=\s|$)", "college"),
    (r"\bhigh\s+scool\b", "high school"),
    (r"\bmadrasha\b", "madrasa"),
    (r"\bmadrasah\b", "madrasa"),
    (r"&", " and "),
    ("হাই স্কুল", "উচ্চ বিদ্যালয়"),
    ("সরকারী", "সরকারি"),
]
_PUNCT = re.compile(r"[^\w\s\u0980-\u09FF]", re.UNICODE)
_SPACE = re.compile(r"\s+")


def normalize_school_name(text):
    s = unicodedata.normalize("NFC", text or "").lower().strip()
    for pattern, repl in _REWRITES:
        s = re.sub(pattern, repl, s)
    s = _PUNCT.sub(" ", s)
    return _SPACE.sub(" ", s).strip()
