#!/usr/bin/env python3
"""Normalize existing roads/{code}-*.csv files: coordinates and duplicates.

Every X and Y that parses as a float is rewritten with 9 fixed decimals
(update_addresses.format_coord); other values stay as they are. Then the
script removes duplicate door-plate rows: government data lists every floor of
a building as its own row (32號, 32號二樓, 32號二樓之1) with the same
coordinates, and update_addresses.dedupe_door_plates keeps one. Only files that
change are rewritten. The `records` column of update_log.csv is refreshed
(last_updated stays as is). road.csv needs no rebuild because no file is
removed.

Usage:
    python scripts/normalize_roads.py 63 65
    python scripts/normalize_roads.py --all
"""

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import update_addresses as ua  # noqa: E402

LOG_HEADER = ["code", "county", "records", "last_updated"]


def round_coords(body: list[list[str]]) -> int:
    """Reformat X and Y in place; returns the number of cells changed."""
    xi, yi = ua.CSV_HEADER.index("X"), ua.CSV_HEADER.index("Y")
    changed = 0
    for row in body:
        for i in (xi, yi):
            if i < len(row):
                try:
                    new = ua.format_coord(float(row[i]))
                except ValueError:
                    continue
                if new != row[i]:
                    row[i] = new
                    changed += 1
    return changed


def dedupe_county(code: str) -> int | None:
    """Normalize one county's road files. Returns its new row count, or None when
    the county has no road files."""
    files = sorted(ua.ROADS_DIR.glob(f"{code}-*.csv"))
    if not files:
        print(f"{code}: no road files")
        return None
    before = removed = after = rewritten = rounded = 0
    for f in files:
        with open(f, encoding="utf-8", newline="") as fh:
            body = list(csv.reader(fh))[1:]
        c = round_coords(body)
        rounded += c
        kept, n = ua.dedupe_door_plates(body)
        before += len(body)
        removed += n
        after += len(kept)
        if n or c:
            with open(f, "w", encoding="utf-8", newline="") as fh:
                w = csv.writer(fh)
                w.writerow(ua.CSV_HEADER)
                w.writerows(kept)
            rewritten += 1
    print(f"{code}: before {before:,}, removed {removed:,}, {rounded:,} coords reformatted, after {after:,}, "
          f"{rewritten} files rewritten")
    return after


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("codes", nargs="*", help="county codes, e.g. 63 65")
    ap.add_argument("--all", action="store_true", help="every county in update_log.csv")
    args = ap.parse_args()
    log_rows = ua._read_update_log()
    codes = sorted(log_rows) if args.all else args.codes
    if not codes:
        ap.error("give county codes or --all")
    for code in codes:
        count = dedupe_county(code)
        if count is not None and code in log_rows:
            log_rows[code]["records"] = str(count)
    with open(ua.ROOT / "update_log.csv", "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(LOG_HEADER)
        for c in sorted(log_rows):
            r = log_rows[c]
            w.writerow([r[k] for k in LOG_HEADER])


if __name__ == "__main__":
    main()
