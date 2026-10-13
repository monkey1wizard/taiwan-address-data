#!/usr/bin/env python3
"""List char_fixes.csv candidates for counties whose source has lost characters.

Government exports write every character outside Big5 as "?". Some sources
use "■" or "？" instead. This script downloads a county's source the same way
update_addresses.py does, collects the village, street and lane values that
contain one of these placeholders, and matches each one
against the official lists in the same town:

  village  NLSC village list   api.nlsc.gov.tw/other/ListVillage
  street   RIS road-name list  www.ris.gov.tw/rs-opendata/api/v1/datastore/ODRP049

A value is "unique" only when exactly one official name matches and every
character at a placeholder position, as the official list writes it, is
outside Big5 and not a private-use code point. NLSC writes a rare character
as "[X]". RIS sometimes uses a CJK compatibility ideograph, which Big5 cannot
encode either. The fixed value is NFC-normalized, so it uses the standard
character. Streets with a numbered section are matched on the road part and
keep the source section. A street such as "■魚坑路瑞興新邨" is matched on its
leading official road name when the rest has no placeholder. Nothing is
written to char_fixes.csv: the output is for review.

With --legacy, values that have no official match (lanes, community names)
are matched against the 2016 import (commit LEGACY_COMMIT) instead. Each row
is joined to the nearest 2016 door plate of the same county within 10 m. A
value is "unique" only when every joined row gives the same 2016 value and
every character at a placeholder position is outside Big5 and not a
private-use code point. The owner accepted this weaker evidence on
2026-10-13.

Usage:
    python scripts/char_fix_candidates.py 彰化縣 屏東縣 --out data/work/charfix
    python scripts/char_fix_candidates.py 彰化縣 --legacy --out data/work/charfix
"""

import argparse
import csv
import hashlib
import io
import json
import re
import subprocess
import unicodedata
import sys
import tarfile
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import update_addresses as ua  # noqa: E402

RIS_YEAR = 115
LEGACY_COMMIT = "c19cba2a9"  # 2016-03-05 import of every road file
LEGACY_RADIUS_M = 10
# Counties whose roads/ files are not produced by update_addresses.py. Their
# candidates come from the tracked road files instead of a government source.
STATIC_COUNTIES = {
    "宜蘭縣": ua.CountyConfig("宜蘭縣", "10002", None, {}),
    "南投縣": ua.CountyConfig("南投縣", "10008", None, {}),
    "臺中市": ua.CountyConfig("臺中市", "66", None, {}),
}
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


def _pattern(value: str) -> str:
    return "".join("(.)" if ch in ua.PLACEHOLDERS else re.escape(ch) for ch in value)


def _ok(groups) -> bool:
    return all(outside_big5(g) and not ua.is_private_use(g) for g in groups)


def match(value: str, pool: set[str]) -> list[str]:
    """Official names matching value, NFC-normalized."""
    pat = re.compile(_pattern(value))
    hits = set()
    for name in pool:
        m = pat.fullmatch(name)
        if m and _ok(m.groups()):
            hits.add(unicodedata.normalize("NFC", name))
    return sorted(hits)


def match_prefix(value: str, pool: set[str]) -> list[str]:
    """Official road names matching the start of value when the rest of value
    has no placeholder, e.g. 𫙮魚坑路 + 瑞興新邨."""
    hits = set()
    for name in pool:
        if len(name) >= len(value):
            continue
        rest = value[len(name):]
        if ua.has_placeholder(rest):
            continue
        m = re.fullmatch(_pattern(value[:len(name)]), name)
        if m and _ok(m.groups()):
            hits.add(unicodedata.normalize("NFC", name) + rest)
    return sorted(hits)


def tracked_road_rows(code: str) -> list[dict]:
    """Rows of every tracked roads/{code}-*.csv in HEAD, including files whose
    names Windows cannot check out."""
    data = subprocess.run(["git", "archive", "HEAD", "roads"], cwd=ua.ROOT,
                          capture_output=True, check=True).stdout
    rows = []
    with tarfile.open(fileobj=io.BytesIO(data)) as tf:
        for m in tf:
            name = m.name.split("/")[-1]
            if m.isfile() and name.startswith(f"{code}-") and name.endswith(".csv"):
                text = tf.extractfile(m).read().decode("utf-8")
                rows += list(csv.DictReader(io.StringIO(text)))
    return rows


def road_tokens(code: str) -> Counter:
    tokens: Counter = Counter()
    for r in tracked_road_rows(code):
        for fld, val in (("street", r["ROAD"] + r["SECTION"]), ("lane", r["LANE"])):
            if ua.has_placeholder(val):
                tokens[(r["TOWN"], fld, val)] += 1
    return tokens


def source_tokens(cfg, s, rare: dict, name_to_code: dict) -> Counter:
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
            if ua.has_placeholder(val):
                tokens[(tcode, fld, val)] += 1
    return tokens


def candidates(cfg, s, out: Path, rare: dict, static: bool = False) -> list[dict]:
    town_names, _ = ua.load_area(cfg)
    name_to_code = {v: k for k, v in town_names.items()}
    nlsc, nlsc_towns = nlsc_villages(s, cfg, out)
    villages = {t: {re.sub(r"\[(.)\]", r"\1", n) for n in ns} for t, ns in nlsc.items()}
    roads = {site: {ua.apply_variants(n, rare.get("RIS路名", {})) for n in ns}
             for site, ns in ris_roads(s, out).items()}
    tokens = road_tokens(cfg.code) if static else source_tokens(cfg, s, rare, name_to_code)
    found = []
    for (tcode, fld, val), n in sorted(tokens.items()):
        town = town_names.get(tcode, "")
        if fld == "village":
            hits = match(val, villages.get(tcode, set()))
        elif fld == "street":
            pool = roads.get(cfg.name + nlsc_towns.get(tcode, town), set())
            hits = match(val, pool)
            road, section = ua.split_section(val)
            if not hits and section and not ua.has_placeholder(section):
                hits = [h + section for h in match(road, pool)]
            if not hits:
                hits = match_prefix(val, pool)
        else:
            hits = []
        status = "unique" if len(hits) == 1 else ("ambiguous" if hits else "none")
        found.append(dict(county=cfg.code, town=tcode, town_name=town, field=fld,
                          source_value=val, rows=n, status=status,
                          candidates="|".join(hits)))
    return found


def _rows_at(rev: str, code: str) -> list[dict]:
    data = subprocess.run(["git", "archive", rev, "roads"], cwd=ua.ROOT,
                          capture_output=True, check=True).stdout
    rows = []
    with tarfile.open(fileobj=io.BytesIO(data)) as tf:
        for m in tf:
            name = m.name.split("/")[-1]
            if m.isfile() and name.startswith(f"{code}-") and name.endswith(".csv"):
                rows += list(csv.DictReader(io.StringIO(tf.extractfile(m).read().decode("utf-8"))))
    return rows


def legacy_candidates(cfg, unresolved: set[tuple[str, str, str]]) -> list[dict]:
    """Match unresolved (town, field, value) keys of one county against the
    2016 import by location. Uses the current road files for coordinates."""
    grid: dict[tuple[int, int], list] = {}
    for r in _rows_at(LEGACY_COMMIT, cfg.code):
        try:
            x, y = float(r["X"]), float(r["Y"])
        except ValueError:
            continue
        grid.setdefault((round(x * 1000), round(y * 1000)), []).append(
            (x, y, {"street": r["ROAD"] + r["SECTION"], "lane": r["LANE"]}))
    seen: dict[tuple[str, str, str], Counter] = {k: Counter() for k in unresolved}
    for r in _rows_at("HEAD", cfg.code):
        for fld, val in (("street", r["ROAD"] + r["SECTION"]), ("lane", r["LANE"])):
            key = (r["TOWN"], fld, val)
            if key not in seen:
                continue
            x, y = float(r["X"]), float(r["Y"])
            best = None
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for cx, cy, old in grid.get((round(x * 1000) + dx, round(y * 1000) + dy), ()):
                        d = ((cx - x) * 101_000) ** 2 + ((cy - y) * 111_000) ** 2
                        if d <= LEGACY_RADIUS_M ** 2 and (best is None or d < best[0]):
                            best = (d, old[fld])
            seen[key][best[1] if best else ""] += 1
    found = []
    for (tcode, fld, val), hits in sorted(seen.items()):
        ok = set()
        for old in hits:
            m = re.fullmatch(_pattern(val), old) if old else None
            if m and _ok(m.groups()):
                ok.add(unicodedata.normalize("NFC", old))
        joined = sum(n for old, n in hits.items() if old)
        status = "unique" if len(ok) == 1 and all(
            unicodedata.normalize("NFC", o) in ok for o in hits if o) else (
            "ambiguous" if ok else "none")
        found.append(dict(county=cfg.code, town=tcode, field=fld, source_value=val,
                          rows=sum(hits.values()), joined=joined, status=status,
                          candidates="|".join(sorted(ok)),
                          legacy_values="|".join(f"{o}:{n}" for o, n in hits.most_common())))
    return found


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("counties", nargs="+")
    ap.add_argument("--out", default=str(ua.ROOT / "data" / "work" / "charfix"))
    ap.add_argument("--legacy", action="store_true",
                    help="match values still holding a placeholder against the 2016 import")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    download = ua.download_bytes

    def cached_download(url: str, s) -> bytes:
        path = out / ("src_" + hashlib.sha256(url.encode()).hexdigest()[:16])
        if path.exists():
            return path.read_bytes()
        raw = download(url, s)
        path.write_bytes(raw)
        print(f"  SHA256 {hashlib.sha256(raw).hexdigest()}")
        return raw
    ua.download_bytes = cached_download
    if args.legacy:
        found = []
        for name in args.counties:
            cfg = STATIC_COUNTIES.get(name) or ua.COUNTIES[name]
            keys = {(r["TOWN"], fld, val) for r in _rows_at("HEAD", cfg.code)
                    for fld, val in (("street", r["ROAD"] + r["SECTION"]), ("lane", r["LANE"]))
                    if ua.has_placeholder(val)}
            found += legacy_candidates(cfg, keys)
        path = out / "legacy_candidates.csv"
        with open(path, "w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(found[0].keys()) if found else ["county"])
            w.writeheader()
            w.writerows(found)
        print(f"wrote {path}")
        return
    s = ua._session()
    rare = ua.load_rare_chars()
    found = []
    for name in args.counties:
        if name in STATIC_COUNTIES:
            found += candidates(STATIC_COUNTIES[name], s, out, rare, static=True)
        else:
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
