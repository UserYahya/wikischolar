"""Read the first sheet of an .xlsx file with the standard library only (an .xlsx is zipped XML).

Used by `manage.py import_banbeis_schools` and scripts/build_thana_seed.py, so it has no Django
imports. Handles shared strings, inline strings and plain values, which is all the BANBEIS export uses.
"""
import re
import zipfile
import xml.etree.ElementTree as ET

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def read_table(path, header_cell):
    """Rows under the first row that contains `header_cell` (e.g. "EIIN_NO"), as dicts keyed by that
    row's headings, plus "_row": the row's number in the spreadsheet. Cells are strings with
    surrounding spaces removed; missing cells are ""."""
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        strings = []
        if "xl/sharedStrings.xml" in names:
            strings = ["".join(t.text or "" for t in si.iter(NS + "t"))
                       for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall(NS + "si")]
        sheet = ET.fromstring(z.read("xl/worksheets/sheet1.xml"))
    grid = []
    for r in sheet.find(NS + "sheetData").findall(NS + "row"):
        row = {"_row": int(r.get("r") or len(grid) + 1)}
        for c in r.findall(NS + "c"):
            col = re.match(r"[A-Z]+", c.get("r")).group()
            kind, v = c.get("t"), c.find(NS + "v")
            if kind == "inlineStr":
                row[col] = "".join(t.text or "" for t in c.iter(NS + "t"))
            elif v is None:
                row[col] = ""
            else:
                row[col] = strings[int(v.text)] if kind == "s" else v.text
        grid.append(row)
    try:
        at = next(i for i, r in enumerate(grid) if header_cell in r.values())
    except StopIteration:
        raise ValueError(f"No header row with {header_cell!r} in {path}.") from None
    cols = [(col, name.strip()) for col, name in grid[at].items() if col != "_row" and name.strip()]
    return [{"_row": r["_row"], **{name: (r.get(col) or "").strip() for col, name in cols}} for r in grid[at + 1:]
            if any((r.get(col) or "").strip() for col, _ in cols)]
