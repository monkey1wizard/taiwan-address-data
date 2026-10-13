#!/usr/bin/env python3
"""List char_fixes.csv candidates for counties whose source contains "?".

Government exports write every character outside Big5 as "?". This script
downloads a county's source the same way update_addresses.py does, collects
the village, street and lane values that contain "?", and matches each one
against the official lists in the same town:

  village  NLSC village list   api.nlsc.gov.tw/other/ListVillage
  street   RIS road-name list  www.ris.gov.tw/rs-opendata/api/v1/datastore/ODRP049

A value is "unique" only when exactly one official name matches and every
character at a "?" position is outside Big5 and not a private-use code point.
Streets with a numbered section are matched on the road part and keep the
source section. Nothing is written to char_fixes.csv: the output is for review.

Usage:
    python scripts/char_fix_candidates.py 彰化縣 屏東縣 --out data/work/charfix
"""

import argparse
import csv
import json
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import update_addresses as ua  # noqa: E402

RIS_YEAR = 115
# NLSC county letters (api.nlsc.gov.tw/other/ListCounty)
NLSC_LETTER = {
    "臺北市": "A", "臺中市": "B", "基隆市": "C", "臺南市": "D", "高雄市": "E",
    "新北市": "F", "宜蘭縣": "G", "桃園市": "H", "嘉義市": "I", "新竹縣": "J",
    "苗栗縣": "K", "南投縣": "M", "彰化縣": "N", "新竹市": "O", "雲林縣": "P",
    "嘉義縣": "Q", "屏東縣": "T", "花蓮縣": "U", "臺東縣": "V", "金門縣": "W",
    "澎湖縣": "X", "連江縣": "Z",
}


def outside_big5(ch: str) -> bool:
    try:
        ch.encode("cp950")
        return False
    except UnicodeEncodeError:
        return True


def fetch_json(s, url: str, cache: Path):
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    r = s.get(url, timeout=60)
    r.raise_for_status()
    data = r.content.decode("utf-8-sig")
    cache.write_text(data, encoding="utf-8")
    return json.loads(data)


def nlsc_villages(s, cfg, out: Path) -> tuple[dict[str, set[str]], dict[str, str]]:
    """({DGBAS town code: {village names}}, {DGBAS town code: current town
    name}) for one county. RIS site ids use current names, e.g. 員林市, while
    area_2014.csv still has 員林鎮."""
    cache = out / f"nlsc_{cfg.code}.json"
    if not cache.exists():
        letter = NLSC_LETTER[cfg.name]
        towns = ET.fromstring(s.get(f"https://api.nlsc.gov.tw/other/ListTown1/{letter}",
                                    timeout=60).content)
        rows = []
        for t in towns.iter("townItem"):
            vs = ET.fromstring(s.get("https://api.nlsc.gov.tw/other/ListVillage/"
                                     f"{letter}/{t.findtext('towncode01')}", timeout=60).content)
            for v in vs.iter("village"):
                rows.append([t.findtext("towncode"), t.findtext("townname"),
                             v.findtext("villageName")])
        cache.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    out_map: dict[str, set[str]] = {}
    names: dict[str, str] = {}
    for towncode, townname, name in json.loads(cache.read_text(encoding="utf-8")):
        tcode = ua.town_code(towncode, cfg)
        out_map.setdefault(tcode, set()).add(name)
        names[tcode] = townname
    return out_map, names


def ris_roads(s, out: Path) -> dict[str, set[str]]:
    """{site_id (county + town name): {road names}} for the whole country."""
    cache = out / f"ris_roads_{RIS_YEAR}.json"
    if not cache.exists():
        base = f"https://www.ris.gov.tw/rs-opendata/api/v1/datastore/ODRP049/{RIS_YEAR}"
        first = json.loads(s.get(base, timeout=60).content.decode("utf-8-sig"))
        rows = list(first["responseData"])
        for page in range(2, int(first["totalPage"]) + 1):
            rows += json.loads(s.get(f"{base}?page={page}", timeout=60)
                               .content.decode("utf-8-sig"))["responseData"]
        rows = [{k.lstrip("﻿"): v for k, v in r.items()} for r in rows]
        cache.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    out_map: dict[str, set[str]] = {}
    for r in json.loads(cache.read_text(encoding="utf-8")):
        out_map.setdefault(r["site_id"], set()).add(r["road"])
    return out_map


def match(value: str, pool: set[str]) -> list[str]:
    pat = re.compile("".join("(.)" if ch == "?" else re.escape(ch) for ch in value))
    hits = []
    for name in pool:
        m = pat.fullmatch(name)
        if m and all(outside_big5(g) and not ua.is_private_use(g) for g in m.groups()):
            hits.append(name)
    return sorted(hits)


def candidates(cfg, s, out: Path, rare: dict) -> list[dict]:
    town_names, _ = ua.load_area(cfg)
    name_to_code = {v: k for k, v in town_names.items()}
    nlsc, nlsc_towns = nlsc_villages(s, cfg, out)
    villages = {t: {ua.apply_variants(n, rare.get("NLSC村里", {})) for n in ns}
                for t, ns in nlsc.items()}
    roads = {site: {ua.apply_variants(n, rare.get("RIS路名", {})) for n in ns}
             for site, ns in ris_roads(s, out).items()}
    rows = ua.load_rows(cfg, s)
    col = dict(cfg.columns)
    available = set(rows[0].keys())
    for canonical, configured in list(col.items()):
        if configured not in available:
            col[canonical] = next((c for c in ua.COLUMN_ALIASES.get(canonical, [])
                                   if c in available), configured)
    variants = rare.get(cfg.code, {})
    tokens: Counter = Counter()
    for row in rows:
        try:
            tcode, village, street, lane, _, _ = ua.source_fields(
                row, col, cfg, name_to_code, variants)
        except (KeyError, ValueError, TypeError):
            continue
        for fld, val in (("village", village), ("street", street), ("lane", lane)):
            if "?" in val:
                tokens[(tcode, fld, val)] += 1
    found = []
    for (tcode, fld, val), n in sorted(tokens.items()):
        town = town_names.get(tcode, "")
        if fld == "village":
            hits = match(val, villages.get(tcode, set()))
        elif fld == "street":
            pool = roads.get(cfg.name + nlsc_towns.get(tcode, town), set())
            hits = match(val, pool)
            road, section = ua.split_section(val)
            if not hits and section and "?" not in section:
                hits = [h + section for h in match(road, pool)]
        else:
            hits = []
        status = "unique" if len(hits) == 1 else ("ambiguous" if hits else "none")
        found.append(dict(county=cfg.code, town=tcode, town_name=town, field=fld,
                          source_value=val, rows=n, status=status,
                          candidates="|".join(hits)))
    return found


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("counties", nargs="+")
    ap.add_argument("--out", default=str(ua.ROOT / "data" / "work" / "charfix"))
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    s = ua._session()
    rare = ua.load_rare_chars()
    found = []
    for name in args.counties:
        found += candidates(ua.COUNTIES[name], s, out, rare)
    path = out / "candidates.csv"
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(found[0].keys()) if found else ["county"])
        w.writeheader()
        w.writerows(found)
    by = Counter()
    for f in found:
        by[(f["county"], f["status"])] += f["rows"]
    for k in sorted(by):
        print(k, by[k])
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
