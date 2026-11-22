"""Ad blockers (EasyList, used by uBlock Origin, Adblock Plus, …) hide any element whose class or id looks
like an ad, on every site. `.adv-text` once hid every text box in the Advanced search for admins with an
ad blocker. Keep class and id names away from ad-like words."""
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

ROOT = Path(settings.BASE_DIR)
# Names that generic ad-block rules match (prefixes, and whole words).
BAD_PREFIXES = ("adv", "ad-", "ad_", "ads-", "ads_", "advert", "sponsor", "banner-ad")
BAD_WORDS = {"ad", "ads", "advert", "adverts", "advertisement", "banner", "sponsor", "sponsored", "promo", "adbox"}


def _names():
    """Every class and id our CSS, JS and templates use, with the file it came from."""
    found = []

    def add(path, names):
        found.extend((n, path.relative_to(ROOT)) for n in names if n)

    for css in (ROOT / "static" / "css").glob("*.css"):
        text = re.sub(r"/\*.*?\*/", "", css.read_text(encoding="utf-8"), flags=re.S)
        text = re.sub(r"url\([^)]*\)", "", text)
        add(css, re.findall(r"[.#](-?[A-Za-z_][\w-]*)(?=[^{}]*\{)", text))
    for js in (ROOT / "static" / "js").glob("*.js"):
        text = js.read_text(encoding="utf-8")
        for value in re.findall(r"""(?:class|className)\s*[:=]\s*["']([^"']+)["']""", text):
            add(js, value.split())
        add(js, re.findall(r"""classList\.(?:add|remove|toggle|contains)\(\s*["']([^"']+)["']""", text))
        add(js, re.findall(r"""\bid\s*:\s*["']([A-Za-z][\w-]*)["']""", text))
        add(js, re.findall(r"""getElementById\(\s*["']([A-Za-z][\w-]*)["']""", text))
    for tpl in [*ROOT.glob("apps/*/templates/**/*.html"), *ROOT.glob("templates/**/*.html")]:
        text = tpl.read_text(encoding="utf-8")
        for value in re.findall(r'class="([^"]*)"', text):
            add(tpl, [w for w in value.split() if "{" not in w and "}" not in w and "%" not in w])
        add(tpl, re.findall(r'\bid="([A-Za-z][\w-]*)"', text))
    return found


def ad_like(name):
    n = name.lower()
    return n in BAD_WORDS or n.startswith(BAD_PREFIXES)


class AdBlockNameTests(SimpleTestCase):
    def test_extraction_sees_the_query_builder(self):
        names = {n for n, _ in _names()}
        self.assertTrue({"qb-text", "qb-cond", "qbBuilder", "stat-bars"} <= names, names)

    def test_no_ad_like_class_or_id_names(self):
        bad = sorted({f"{n} ({path})" for n, path in _names() if ad_like(n)})
        self.assertEqual(bad, [], "Ad blockers hide elements with these names; rename them.")

    def test_rule(self):
        for name in ("adv-text", "adv-top", "advBuilder", "ad", "ads-box", "banner"):
            self.assertTrue(ad_like(name), name)
        for name in ("qb-text", "add-row", "address", "admin-list", "adjust", "heard-banner-note", "badge"):
            self.assertFalse(ad_like(name), name)
