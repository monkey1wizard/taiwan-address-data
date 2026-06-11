#!/usr/bin/env python3
"""Build area_2015.csv from the current roads/ data.

area_*.csv files are layered lookup tables used by address.js to resolve
address prefixes (county/district/village names) to DGBAS codes. Newer
layers take priority: custom > 2015 > 2014 > 2010 > 1984.

This script extracts every unique (display-name → DGBAS code) mapping
present in the current roads/ CSVs, then writes only the entries that are
NEW or CHANGED relative to area_2014.csv — keeping the output small and
the diff reviewable.

Format of each area CSV (same as the existing ones):
    name,dgbas_id
    新北市板橋區,6500100
    新北市板橋區港嘴里,6500100-050

District rows have a 7-digit dgbas_id; village rows have an 11-char id
(7-digit town code + "-" + 3-digit village sequence).

Usage:
    python scripts/build_area_2015.py [--dry-run]
"""

import argparse
import csv
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ROADS_DIR = ROOT / "roads"
AREA_2014 = ROOT / "area_2014.csv"
AREA_2026 = ROOT / "area_2015.csv"

# Maps county code prefix → county display name (must match update_addresses.py)
COUNTY_NAMES = {
    "63": "臺北市", "64": "高雄市", "65": "新北市", "66": "臺中市",
    "67": "臺南市", "68": "桃園市",
    "09007": "連江縣", "09020": "金門縣",
    "10002": "宜蘭縣", "10004": "新竹縣", "10005": "苗栗縣",
    "10007": "彰化縣", "10008": "南投縣", "10009": "雲林縣",
    "10010": "嘉義縣", "10012": "嘉義市", "10013": "屏東縣",
    "10014": "臺東縣", "10015": "花蓮縣", "10016": "澎湖縣",
    "10017": "基隆市", "10018": "新竹市", "10020": "嘉義市",
}


def load_existing(path: Path) -> dict[str, str]:
    """Return name→code dict from an area CSV."""
    result: dict[str, str] = {}
    if not path.exists():
        return result
    with open(path, encoding="utf-8") as f:
        for row in csv.reader(f):
            if len(row) >= 2 and row[1].strip() and row[1].strip() != "dgbas_id":
                result[row[0].strip()] = row[1].strip()
    return result


def extract_from_roads() -> dict[str, str]:
    """
    Scan every roads/*.csv and extract (display_name → dgbas_id) mappings.

    Each road CSV row has:
        FULL_ADDR, COUNTY, TOWN, VILLAGE, NEIGHBORHOOD, ROAD, ...
    where:
        COUNTY  = 2-or-5-digit county code  (e.g. 65)
        TOWN    = 7-digit DGBAS town code   (e.g. 6500100)
        VILLAGE = 11-char village code      (e.g. 6500100-050)
        FULL_ADDR starts with county_name + district_name + village_name

    We reconstruct:
        "新北市板橋區"       → "6500100"
        "新北市板橋區港嘴里"  → "6500100-050"
    """
    mapping: dict[str, str] = {}

    for csv_path in ROADS_DIR.glob("*.csv"):
        county_code = csv_path.stem.split("-", 1)[0]
        county_name = COUNTY_NAMES.get(county_code)
        if not county_name:
            continue

        with open(csv_path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                full = row.get("FULL_ADDR", "").strip()
                town_code = row.get("TOWN", "").strip()
                village_code = row.get("VILLAGE", "").strip()

                if not full.startswith(county_name):
                    continue
                rest = full[len(county_name):]  # e.g. 板橋區港嘴里5鄰...

                # Extract district name: first N chars ending with 區/市/鎮/鄉
                dm = re.match(r"^(.+?[區市鎮鄉])", rest)
                if not dm:
                    continue
                district = dm.group(1)
                district_key = county_name + district

                if len(town_code) == 7:
                    mapping[district_key] = town_code

                # Extract village name: chars after district up to first digit/鄰
                after_district = rest[len(district):]
                vm = re.match(r"^([^\d鄰]+里|[^\d鄰]+村)", after_district)
                if vm and village_code and "-" in village_code and not village_code.endswith("-000"):
                    village = vm.group(1)
                    village_key = district_key + village
                    mapping[village_key] = village_code

    return mapping


def main() -> None:
    ap = argparse.ArgumentParser(description="Build area_2015.csv from roads/ data")
    ap.add_argument("--dry-run", action="store_true",
                    help="print new entries without writing")
    args = ap.parse_args()

    print("Scanning roads/ …")
    extracted = extract_from_roads()
    print(f"  {len(extracted):,} unique name→code mappings found in roads/")

    existing_2014 = load_existing(AREA_2014)
    print(f"  {len(existing_2014):,} entries in area_2014.csv")

    new_entries: list[tuple[str, str]] = []
    changed_entries: list[tuple[str, str]] = []
    for name, code in sorted(extracted.items()):
        old = existing_2014.get(name)
        if old is None:
            new_entries.append((name, code))
        elif old != code:
            changed_entries.append((name, code))

    print(f"  {len(new_entries):,} new entries, {len(changed_entries):,} changed entries")

    all_new = new_entries + changed_entries
    if not all_new:
        print("Nothing to write — area_2014.csv already covers all mappings.")
        return

    if args.dry_run:
        print("\nDry run — would write:")
        for name, code in all_new[:40]:
            print(f"  {name},{code}")
        if len(all_new) > 40:
            print(f"  … and {len(all_new)-40} more")
        return

    # Load existing area_2015 to merge (avoid duplicates on re-run)
    existing_2026 = load_existing(AREA_2026)
    merged = {**existing_2026, **{n: c for n, c in all_new}}
    rows = sorted(merged.items(), key=lambda x: x[0])

    with open(AREA_2026, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["name", "dgbas_id"])
        w.writerows(rows)

    print(f"Written {len(rows):,} entries to area_2015.csv")


if __name__ == "__main__":
    main()
