#!/usr/bin/env python3
"""Apply char_fixes.csv and rare_chars.csv to counties that update_addresses.py
does not produce (宜蘭縣 10002, 南投縣 10008, 臺中市 66).

Their roads/ files come from the 2016 import or a TGOS snapshot, so there is no
government source to rerun. This script rewrites the tracked road files of one
county in place: it fixes ROAD/SECTION and LANE values listed for each town,
replaces the matching text in FULL_ADDR, and regroups the rows by the fixed
road name. A "full_addr" fix only replaces text inside FULL_ADDR, for rows
whose road name exists only there. Files whose names contain "?" cannot exist on Windows, so they are
read from git HEAD and removed from the index with `git rm --cached --sparse`.

Usage:
    python scripts/fix_static_roads.py 10002 10008 66
"""

import argparse
import csv
import io
import subprocess
import sys
import tarfile
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import update_addresses as ua  # noqa: E402

TEXT_FIELDS = ("FULL_ADDR", "ROAD", "SECTION", "LANE", "ALLEY", "NUMBER")


def head_files(code: str) -> dict[str, list[dict]]:
    """{file name: rows} for every tracked roads/{code}-*.csv in HEAD."""
    data = subprocess.run(["git", "archive", "HEAD", "roads"], cwd=ua.ROOT,
                          capture_output=True, check=True).stdout
    files: dict[str, list[dict]] = {}
    with tarfile.open(fileobj=io.BytesIO(data)) as tf:
        for m in tf:
            name = m.name.split("/")[-1]
            if m.isfile() and name.startswith(f"{code}-") and name.endswith(".csv"):
                text = tf.extractfile(m).read().decode("utf-8")
                files[name] = list(csv.DictReader(io.StringIO(text)))
    return files


def fix_row(row: dict, fixes: dict, variants: dict) -> bool:
    """Fix one road-file row in place. Returns True when anything changed."""
    before = dict(row)
    for k in TEXT_FIELDS:
        row[k] = ua.apply_variants(row[k], variants)
    town = row["TOWN"]
    street = row["ROAD"] + row["SECTION"]
    new_street = fixes.get((town, "street", street))
    if new_street is not None:
        row["ROAD"], row["SECTION"] = ua.split_section(new_street)
        row["FULL_ADDR"] = row["FULL_ADDR"].replace(street, new_street, 1)
    for (t, fld, old), new in fixes.items():
        if t == town and fld == "full_addr" and old in row["FULL_ADDR"]:
            row["FULL_ADDR"] = row["FULL_ADDR"].replace(old, new, 1)
    new_lane = fixes.get((town, "lane", row["LANE"]))
    if new_lane is not None:
        row["FULL_ADDR"] = row["FULL_ADDR"].replace(row["LANE"], new_lane, 1)
        row["LANE"] = new_lane
    prefix = row["ROAD"] + row["SECTION"] + row["LANE"] + row["ALLEY"]
    new_number = fixes.get((town, "number", prefix + row["NUMBER"]))
    if new_number is not None and new_number.startswith(prefix):
        new_number = new_number[len(prefix):]
        row["FULL_ADDR"] = row["FULL_ADDR"][::-1].replace(
            row["NUMBER"][::-1], new_number[::-1], 1)[::-1]
        row["NUMBER"] = new_number
    return row != before


def format_coords(row: dict) -> None:
    """Rewrite X and Y with format_coord; unparsable values stay as they are."""
    for k in ("X", "Y"):
        try:
            row[k] = ua.format_coord(float(row[k]))
        except ValueError:
            pass


def fix_county(code: str) -> None:
    fixes = ua.load_char_fixes(code)
    variants = ua.load_rare_chars().get(code, {})
    old = head_files(code)
    new: dict[str, list[dict]] = defaultdict(list)
    changed_rows = 0
    for name in sorted(old):
        for row in old[name]:
            key = row["ROAD"] + row["SECTION"] + row["LANE"] + row["ALLEY"] + row["NUMBER"]
            if (row["TOWN"], "drop", key) in fixes:
                changed_rows += 1
                continue
            changed_rows += fix_row(row, fixes, variants)
            format_coords(row)
            new[f"{code}-{ua.safe_filename(row['ROAD'])}.csv"].append(row)

    dedupe_removed = 0
    for name in list(new):
        recs, n = ua.dedupe_door_plates([[r[k] for k in ua.CSV_HEADER] for r in new[name]])
        if n:
            new[name] = [dict(zip(ua.CSV_HEADER, rec)) for rec in recs]
            dedupe_removed += n

    written = [n for n in new if n not in old or new[n] != old_rows(code, n)]
    removed = [n for n in old if n not in new]
    for name in written:
        with open(ua.ROADS_DIR / name, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(ua.CSV_HEADER)
            w.writerows([r[k] for k in ua.CSV_HEADER] for r in new[name])
    for name in removed:
        path = ua.ROADS_DIR / name
        if path.exists():
            path.unlink()
        else:
            subprocess.run(["git", "rm", "-q", "--cached", "--sparse", "--",
                            f"roads/{name}"], cwd=ua.ROOT, check=True)
    left = sum(ua.has_placeholder(r["ROAD"] + r["SECTION"] + r["LANE"])
               for rows in new.values() for r in rows)
    print(f"{code}: {changed_rows} rows changed, {len(written)} files written, "
          f"{len(removed)} files removed, {left} rows still have a placeholder "
          f"in ROAD/SECTION/LANE, {dedupe_removed} door-plate duplicates removed")
    for name in sorted(set(written) - set(old)):
        print(f"  + {name}")
    for name in sorted(removed):
        print(f"  - {name}")


_HEAD_CACHE: dict[str, dict[str, list[dict]]] = {}


def old_rows(code: str, name: str) -> list[dict]:
    if code not in _HEAD_CACHE:
        _HEAD_CACHE[code] = head_files(code)
    return _HEAD_CACHE[code].get(name, [])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("codes", nargs="+", help="county codes, e.g. 10002 66")
    for code in ap.parse_args().codes:
        fix_county(code)
    print("Rebuild road.csv from the tracked file list after staging.")


if __name__ == "__main__":
    main()
