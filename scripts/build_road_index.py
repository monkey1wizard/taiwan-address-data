#!/usr/bin/env python3
"""Rebuild road.csv from the current contents of roads/.

road.csv is a flat index used by address.js to map county codes to road names
before opening individual per-road CSV files. It must stay in sync with roads/.

Usage:
    python scripts/build_road_index.py
"""

import csv
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ROADS_DIR = ROOT / "roads"
ROAD_CSV = ROOT / "road.csv"


def build() -> None:
    entries: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    for path in sorted(ROADS_DIR.glob("*.csv")):
        stem = path.stem  # e.g. "65-中山路" or "65-"
        parts = stem.split("-", 1)
        if len(parts) != 2:
            continue
        county_code, road_name = parts[0], parts[1]
        key = (county_code, road_name)
        if key not in seen:
            seen.add(key)
            entries.append(key)

    with open(ROAD_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["county_id", "road"])
        w.writerows(entries)

    print(f"road.csv rebuilt: {len(entries):,} entries across "
          f"{len({c for c, _ in entries})} counties")


if __name__ == "__main__":
    build()
