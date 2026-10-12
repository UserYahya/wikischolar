"""Build the district + thana lists from the government's BANBEIS school list (e-survey 2024).

    python scripts/build_thana_seed.py map banbase-school-data.xlsx OLD_SEED.json  # writes data/thana_mapping.csv
    python scripts/build_thana_seed.py seed                                       # writes data/reference_seed.json

OLD_SEED.json is the seed with the previous "Upazila / Area" list, e.g.
`git show a1dc1ba:data/reference_seed.json > /tmp/old_seed.json` (main before the thana change).
`map` reads the sheet (DISTRICT_NAME, THANA_NAME columns) and that old seed, and drafts
data/thana_mapping.csv: one row per thana with its Bangla name and the old "Upazila / Area" it
replaces, plus one `retired` row per old area that has no successor (its students and schools move
to the row's `thana`). Review that file by hand (fix `replaces`, `thana_bn`, retired targets), then
run `seed` to turn it into data/reference_seed.json. Migration reference.0007 reads the same CSV to
rename, add and retire rows in an existing database.

The thana list is: the sheet's thanas (names cleaned up), the newer upazilas the 2024 sheet doesn't
have yet, the cantonments, and one "Other thana (not listed)" per district.
Standard library only, so it runs anywhere.
"""
import csv
import difflib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from apps.reference.xlsx import read_table  # noqa: E402  (standard library only)

SEED = ROOT / "data" / "reference_seed.json"
MAPPING = ROOT / "data" / "thana_mapping.csv"
COLUMNS = ["district_code", "district", "thana", "thana_bn", "group", "group_bn", "source", "replaces",
           "sheet_name", "sheet_schools", "note"]

# Sheet district spellings that are typos, not official names.
DISTRICT_FIXES = {"Brahamanbaria": "Brahmanbaria", "Coxs Bazar": "Cox's Bazar", "Nawabganj": "Chapainawabganj"}
# Government spelling -> our district code, where the name changed (everything else matches by name).
RENAMED_DISTRICTS = {"Barishal": "barisal", "Bogura": "bogra", "Chattogram": "chittagong", "Cumilla": "comilla",
                     "Jashore": "jessore", "Khagrachhari": "khagrachari", "Maulvibazar": "moulvibazar",
                     "Netrakona": "netrokona", "Norail": "narail"}
OTHER = ("Other thana (not listed)", "অন্য থানা (তালিকায় নেই)")
CANTONMENT = ("Cantonment", "সেনানিবাস")

# Old area name -> sheet thana (cleaned), per district code, where the spelling differs too much
# for automatic matching or the name changed.
ALIASES = {
    "barisal": {"Barisal Sadar": "Barisal Sadar (Kotwali)"},
    "chandpur": {"Matlab North": "Matlab Uttar", "Matlab South": "Matlab Dakshin"},
    "chittagong": {"Karnafuli": "Karnaphuli", "Bandar": "Chittagong Port"},
    "coxs-bazar": {"Ukhiya": "Ukhia"},
    "comilla": {"Comilla Sadar": "Comilla Adarsha Sadar", "Sadarsouth": "Comilla Sadar Dakshin"},
    "gaibandha": {"Phulchari": "Fulchhari"},
    "jessore": {"Jessore Sadar": "Kotwali"},
    "khulna": {"Dakop": "Dacope", "Fultola": "Phultala", "Paikgasa": "Paikgachha", "Botiaghata": "Batiaghata",
               "Digholia": "Dighalia", "Rupsha": "Rupsa"},
    "kurigram": {"Rowmari": "Raumari"},
    "lakshmipur": {"Raipur": "Roypur"},
    "narsingdi": {"Raipura": "Roypura"},
    "netrokona": {"Mohongonj": "Mohanganj"},
    "nilphamari": {"Syedpur": "Saidpur", "Kishorganj": "Kishoreganj"},
    "noakhali": {"Senbug": "Senbagh"},
    "pirojpur": {"Nesarabad": "Nesarabad (Swarupkati)", "Zianagar": "Indurkani"},
    "rangamati": {"Belaichari": "Belai Chhari", "Juraichari": "Jurai Chhari", "Kawkhali": "Kawkhali (Betbunia)"},
    "sirajganj": {"Raigonj": "Royganj"},
    "sunamganj": {"South Sunamganj": "Dakshin Sunamganj", "Shalla": "Sulla"},
    "dhaka": {"Bhashantek": "Bhasan Tek", "Vatara": "Bhatara", "Airport": "Biman Bandar", "Chawkbazar": "Chak Bazar",
              "Kamrangirchar": "Kamrangir Char", "Mirpur Model": "Mirpur", "Mugda": "Mugda Para",
              "Paltan Model": "Paltan", "Ramna Model": "Ramna", "Tejgaon Industrial Area": "Tejgaon Ind. Area",
              "Uttarkhan": "Uttar Khan", "Uttara East": "Uttara", "Uttara West": "Uttara Paschim"},
}
# Old city-corporation areas the sheet doesn't list: the thana that covers them, where that's clear.
# Anything else retired moves to the district's "Other thana".
RETIRE_TO = {
    "gazipur": dict.fromkeys(["Basan", "Konabari", "Kashimpur", "Gacha", "Pubail", "Tongi East", "Tongi West"],
                             "Gazipur Sadar"),
    "rangpur": dict.fromkeys(["Kotwali", "Tajhat", "Mahiganj", "Parshuram", "Haragach", "Hazirhat"], "Rangpur Sadar"),
    "sylhet": dict.fromkeys(["Kotwali", "Jalalabad", "Shah Paran", "Moglabazar", "Airport"], "Sylhet Sadar"),
    "barisal": dict.fromkeys(["Kotwali", "Airport", "Kawnia", "Bandar"], "Barisal Sadar (Kotwali)"),
    "bogra": {"Bogura City Corporation": "Bogra Sadar"},
    "comilla": {"Cumilla City Corporation": "Comilla Adarsha Sadar"},
    "mymensingh": {"Mymensingh City Corporation": "Mymensingh Sadar"},
    "narayanganj": {"Narayanganj City Corporation": "Narayanganj Sadar"},
}
# Bangla for sheet thanas with no predecessor in the old list.
NEW_BANGLA = {("dhaka", "Cantonment"): "ক্যান্টনমেন্ট"}
# Upazilas created after the 2024 survey: kept from the current seed although the sheet lacks them.
NEWER_UPAZILAS = {
    "bogra": ["Mokamtola"], "chittagong": ["Fatikchhari North"], "coxs-bazar": ["Eidgaon", "Matamuhuri"],
    "comilla": ["Bangra"], "lakshmipur": ["Chandraganj"], "madaripur": ["Dasar"],
    "mymensingh": ["South Gafargaon"], "sunamganj": ["Madhyanagar"], "thakurgaon": ["Bhully", "Ruhia"],
}


def clean_thana(name):
    """'Kaptai  Upazila' -> 'Kaptai', 'Belai Chhari  Upazi' -> 'Belai Chhari', 'Uttara  Paschim' ->
    'Uttara Paschim'. The sheet cuts names at 19 characters, so a cut-off ' Upazila' is dropped too."""
    name = " ".join(name.split())
    name = re.sub(r"\s+(U|Up|Upa|Upaz|Upazi|Upazil|Upazila)$", "", name)
    return name.strip()


def _key(name):
    return re.sub(r"[^a-z]", "", name.casefold())


def read_sheet(path):
    """(district, raw thana) -> number of schools, from the xlsx."""
    out = Counter()
    for r in read_table(path, "DISTRICT_NAME"):
        if r["DISTRICT_NAME"]:
            out[(DISTRICT_FIXES.get(r["DISTRICT_NAME"], r["DISTRICT_NAME"]), r["THANA_NAME"])] += 1
    return out


def draft_mapping(xlsx, old_seed):
    seed = json.loads(Path(old_seed).read_text(encoding="utf-8"))
    sheet = read_sheet(xlsx)
    by_district = defaultdict(Counter)
    for (district, thana), n in sheet.items():
        by_district[district][thana] += n
    old_districts = list(seed["districts"])
    # Sheet district -> seed district: same name, else closest spelling (Chattogram ~ Chittagong).
    old_by_key = {_key(d["name"]): d for d in old_districts}
    by_code = {d["code"]: d for d in old_districts}
    matched, rows = {}, []
    for name in by_district:
        d = old_by_key.get(_key(name)) or by_code.get(RENAMED_DISTRICTS.get(name, ""))
        if not d:
            sys.exit(f"Sheet district {name!r} doesn't match any district in the seed.")
        if d["code"] in matched:
            sys.exit(f"Districts {matched[d['code']]!r} and {name!r} both match {d['name']!r}.")
        matched[d["code"]] = name
    missing = [d["name"] for d in old_districts if d["code"] not in matched]
    if missing:
        sys.exit(f"Seed districts not in the sheet: {missing}")

    for d in sorted(old_districts, key=lambda d: matched[d["code"]]):
        code, name = d["code"], matched[d["code"]]
        olds = [dict(o, group=o.get("group", "")) for o in d.get("upazilas", []) + d.get("areas", [])]
        place = [o for o in olds if o["group"] not in ("Cantonment", "Other")]  # upazilas + city thanas
        by_name = {o["name"]: o for o in place}
        by_key = {_key(o["name"]): o for o in place}
        aliases = {new: old for old, new in ALIASES.get(code, {}).items()}
        used = set()
        sheet_thanas = sorted(by_district[name].items(), key=lambda kv: clean_thana(kv[0]))
        pending = []
        for raw, n in sheet_thanas:
            thana = clean_thana(raw)
            old, source = None, "sheet-new"
            if thana in aliases and aliases[thana] in by_name:
                old, source = by_name[aliases[thana]], "sheet-alias"
            elif _key(thana) in by_key:
                old, source = by_key[_key(thana)], "sheet-exact"
            if old:
                used.add(old["name"])
            pending.append([raw, n, thana, old, source])
        for row in pending:  # spelling variants among what's left, closest first
            if row[3]:
                continue
            free = [k for k, o in by_key.items() if o["name"] not in used]
            near = difflib.get_close_matches(_key(row[2]), free, 1, 0.8)
            if near:
                row[3], row[4] = by_key[near[0]], "sheet-variant"
                used.add(row[3]["name"])
        for raw, n, thana, old, source in pending:
            rows.append({"district_code": code, "district": name, "thana": thana,
                         "thana_bn": (old or {}).get("name_bn", "") or NEW_BANGLA.get((code, thana), ""), "group": "", "group_bn": "", "source": source,
                         "replaces": (old or {}).get("name", ""), "sheet_name": raw, "sheet_schools": n,
                         "note": "check: spelling variant" if source == "sheet-variant" else
                                 ("no Bangla yet" if not old else "")})
        for new_name in NEWER_UPAZILAS.get(code, []):
            old = by_name[new_name]
            used.add(new_name)
            rows.append({"district_code": code, "district": name, "thana": new_name, "thana_bn": old.get("name_bn", ""),
                         "group": "", "group_bn": "", "source": "newer-upazila", "replaces": new_name,
                         "sheet_name": "", "sheet_schools": 0, "note": "upazila created after the 2024 survey"})
        for o in olds:
            if o["group"] == "Cantonment":
                used.add(o["name"])
                rows.append({"district_code": code, "district": name, "thana": o["name"], "thana_bn": o.get("name_bn", ""),
                             "group": CANTONMENT[0], "group_bn": CANTONMENT[1], "source": "cantonment",
                             "replaces": o["name"], "sheet_name": "", "sheet_schools": 0, "note": ""})
        old_other = next((o["name"] for o in olds if o["group"] == "Other"), "")
        used.add(old_other)
        rows.append({"district_code": code, "district": name, "thana": OTHER[0], "thana_bn": OTHER[1],
                     "group": "Other", "group_bn": "অন্যান্য", "source": "other", "replaces": old_other,
                     "sheet_name": "", "sheet_schools": 0, "note": ""})
        for o in olds:
            if o["name"] not in used:
                target = RETIRE_TO.get(code, {}).get(o["name"], OTHER[0])
                rows.append({"district_code": code, "district": name, "thana": target, "thana_bn": "",
                             "group": "", "group_bn": "", "source": "retired", "replaces": o["name"],
                             "sheet_name": "", "sheet_schools": 0,
                             "note": "old area not in the government list; its students/schools move to `thana`"})
    with MAPPING.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, COLUMNS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    counts = Counter(r["source"] for r in rows)
    print(f"Wrote {MAPPING.relative_to(ROOT)}: {dict(counts)}")
    print("Without Bangla:", sum(1 for r in rows if r["source"] != "retired" and not r["thana_bn"]))


def build_seed():
    seed = json.loads(SEED.read_text(encoding="utf-8"))
    rows = list(csv.DictReader(MAPPING.open(encoding="utf-8")))
    by_code = defaultdict(list)
    for r in rows:
        if r["source"] != "retired":
            by_code[r["district_code"]].append(r)
    for d in seed["districts"]:
        thanas = by_code[d["code"]]
        if not thanas:
            sys.exit(f"No thanas for {d['code']} in the mapping.")
        d["name"] = thanas[0]["district"]
        d.pop("upazilas", None)
        d.pop("areas", None)
        d["thanas"] = [{k: v for k, v in (("name", r["thana"]), ("name_bn", r["thana_bn"]),
                                          ("group", r["group"]), ("group_bn", r["group_bn"])) if v}
                       for r in thanas]
        names = [t["name"] for t in d["thanas"]]
        if len(names) != len(set(names)):
            sys.exit(f"Repeated thana in {d['name']}: {[n for n in names if names.count(n) > 1]}")
    seed["_comment"] = (
        "Seed data only. Loaded by `manage.py seed_reference`; migration reference.0007 applies "
        "data/thana_mapping.csv to existing databases. After seeding, region assignment is managed in the "
        "database via the admin dashboard; re-running the seed never overwrites dashboard edits unless "
        "--reset-region-assignments is passed. Districts and thanas: BANBEIS institution list, e-survey 2024 "
        "(three district typos fixed: Brahmanbaria, Cox's Bazar, Chapainawabganj), plus the upazilas created "
        "after that survey, the cantonments (group = Cantonment) and one \"Other thana (not listed)\" per "
        "district (group = Other). Bangla names carried over from the previous upazila list where the place "
        "matches. Built by scripts/build_thana_seed.py.")
    SEED.write_text(json.dumps(seed, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"Wrote {SEED.relative_to(ROOT)}: {len(seed['districts'])} districts, "
          f"{sum(len(d['thanas']) for d in seed['districts'])} thanas.")


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "map":
        draft_mapping(sys.argv[2], sys.argv[3])
    elif len(sys.argv) == 2 and sys.argv[1] == "seed":
        build_seed()
    else:
        sys.exit(__doc__)
