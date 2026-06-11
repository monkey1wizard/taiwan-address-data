#!/usr/bin/env python3
"""
Update Taipei (63) road address coordinate files from data.gov.tw dataset 155472.

Source:   https://data.gov.tw/dataset/155472
Provider: Taipei City Civil Affairs Bureau (臺北市政府民政局)
Updates:  Monthly

Usage:
    pip install requests pyproj
    python update_taipei.py
"""

import csv
import io
import re
import ssl
import sys
from collections import defaultdict
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.poolmanager import PoolManager

# ── Constants ─────────────────────────────────────────────────────────────────

DATASET_ID = "155472"
API_URL = f"https://data.gov.tw/api/v2/rest/dataset/{DATASET_ID}"

ROADS_DIR = Path(__file__).parent / "roads"
AREA_CSV = Path(__file__).parent / "area_2014.csv"

COUNTY_CODE = "63"
COUNTY_NAME = "臺北市"

# Map old 7-digit DGBAS town codes → district names
TOWN_NAMES = {
    "6300100": "松山區",
    "6300200": "信義區",
    "6300300": "大安區",
    "6300400": "中山區",
    "6300500": "中正區",
    "6300600": "大同區",
    "6300700": "萬華區",
    "6300800": "文山區",
    "6300900": "南港區",
    "6301000": "內湖區",
    "6301100": "士林區",
    "6301200": "北投區",
}

CSV_HEADER = [
    "FULL_ADDR", "COUNTY", "TOWN", "VILLAGE", "NEIGHBORHOOD",
    "ROAD", "SECTION", "LANE", "ALLEY", "SUB_ALLEY", "TONG",
    "NUMBER", "X", "Y",
]

# ── Helpers ───────────────────────────────────────────────────────────────────

def new_to_old_town(new_code: str) -> str:
    """Convert MOI 8-digit district code (63000XXX) to DGBAS 7-digit (630XXXX).

    The last 3 digits of the new code * 10 give the last 4 digits of the old code:
      63000010 → seq=010=10 → 10*10=100 → 0100 → 6300100
      63000120 → seq=120    → 120*10=1200 → 6301200
    """
    seq = int(new_code[-3:])
    return "630" + str(seq * 10).zfill(4)


def fullwidth_to_halfwidth(s: str) -> str:
    """Convert full-width ASCII characters (Ａ-ｚ, ０-９) to half-width."""
    return "".join(
        chr(ord(c) - 0xFEE0) if 0xFF01 <= ord(c) <= 0xFF5E else c
        for c in s
    )


def normalize(s) -> str:
    return fullwidth_to_halfwidth((s or "").strip())


# Trailing road section, e.g. "民生東路五段" → ("民生東路", "五段").
# Source data embeds the section in the 街路段 column; the road-grouped output
# files (and the Taichung reference format) keep ROAD and SECTION separate.
_SECTION_RE = re.compile(r"^(.*?)([一二三四五六七八九十\d]+段)$")


def split_section(street: str) -> tuple[str, str]:
    """Split a combined street string into (road, section). Section is '' if none."""
    street = (street or "").strip()
    m = _SECTION_RE.match(street)
    if m and m.group(1):  # require a non-empty road before the section
        return m.group(1), m.group(2)
    return street, ""


def load_village_lookup() -> dict:
    """Build (old_town_code, village_name) → village_code from area_2014.csv."""
    lookup: dict[tuple[str, str], str] = {}
    prefix = COUNTY_NAME
    with open(AREA_CSV, encoding="utf-8") as f:
        for row in csv.reader(f):
            if len(row) < 2:
                continue
            name, code = row[0].strip(), row[1].strip()
            if "-" not in code or not code.startswith("630"):
                continue
            if not name.startswith(prefix):
                continue
            rest = name[len(prefix):]  # e.g. "北投區一德里"
            for town_code, district in TOWN_NAMES.items():
                if rest.startswith(district):
                    village = rest[len(district):]
                    if village:
                        lookup[(town_code, village)] = code
                    break
    return lookup


class _RelaxedStrictAdapter(HTTPAdapter):
    """TLS adapter that keeps FULL certificate-chain and hostname verification,
    but clears OpenSSL's VERIFY_X509_STRICT flag.

    Python 3.13+ enables X509_STRICT by default, which rejects otherwise-valid
    certificates that omit a Subject Key Identifier extension — a pedantic RFC 5280
    check that browsers do not enforce. Several Taiwan government sites (e.g.
    data.taipei, issued by the publicly-trusted TWCA CA) trip this check.

    This is NOT `verify=False`: the CA chain and hostname are still fully verified,
    so a man-in-the-middle cannot impersonate the server without a genuine
    TWCA-issued certificate for the real hostname. Only the non-critical strict
    extension check is relaxed.
    """

    def init_poolmanager(self, connections, maxsize, block=False, **kwargs):
        ctx = ssl.create_default_context()
        ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT  # relax ONLY the strict check
        self.poolmanager = PoolManager(
            num_pools=connections, maxsize=maxsize, block=block,
            ssl_context=ctx, **kwargs,
        )


def _session() -> requests.Session:
    """A requests Session that keeps full TLS verification (CA chain + hostname)
    while tolerating the missing-SKI quirk of some Taiwan government certs."""
    s = requests.Session()
    s.mount("https://", _RelaxedStrictAdapter())
    return s


def get_download_url() -> str:
    """Fetch current CSV download URL from the data.gov.tw API."""
    resp = _session().get(API_URL, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    for dist in data.get("result", {}).get("distribution", []):
        if dist.get("resourceFormat", "").upper() == "CSV":
            url = dist.get("resourceDownloadUrl", "")
            if url:
                return url
    raise RuntimeError(f"No CSV resource found in dataset {DATASET_ID}")


def download_text(url: str) -> str:
    """Stream-download the CSV and return as a decoded string."""
    print(f"Downloading from:\n  {url}")
    resp = _session().get(url, timeout=600, stream=True)
    resp.raise_for_status()
    chunks = []
    total = 0
    for chunk in resp.iter_content(chunk_size=1024 * 1024):
        chunks.append(chunk)
        total += len(chunk)
        print(f"\r  {total / 1024 / 1024:.1f} MB", end="", flush=True)
    print()
    raw = b"".join(chunks)
    # Try UTF-8 with BOM, then Big5 as fallback (government data is sometimes Big5)
    for enc in ("utf-8-sig", "utf-8", "big5"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    try:
        from pyproj import Transformer
    except ImportError:
        print("ERROR: pyproj is required.  Run:  pip install pyproj", file=sys.stderr)
        sys.exit(1)

    transformer = Transformer.from_crs("EPSG:3826", "EPSG:4326", always_xy=True)

    print("Resolving download URL…")
    url = get_download_url()

    text = download_text(url)

    print("Loading village code lookup…")
    village_lookup = load_village_lookup()

    print("Processing records…")
    road_groups: dict[str, list[list]] = defaultdict(list)
    skipped = 0

    reader = csv.DictReader(io.StringIO(text))
    for i, row in enumerate(reader, 1):
        try:
            new_town = (row.get("鄉鎮市區代碼") or "").strip()
            town = new_to_old_town(new_town)
            village_name = (row.get("村里") or "").strip()
            village = village_lookup.get((town, village_name), town + "-000")

            nei_raw = (row.get("鄰") or "").strip().lstrip("0") or "0"
            neighborhood = (nei_raw + "鄰") if nei_raw != "0" else ""

            # 街路段 embeds the section (e.g. 民生東路五段); split it out.
            road, section = split_section((row.get("街路段") or "").strip())
            lane = normalize(row.get("巷"))
            alley = normalize(row.get("弄"))
            number = normalize(row.get("號"))

            lon, lat = transformer.transform(
                float(row["橫座標"]), float(row["縱座標"])
            )
        except (KeyError, ValueError, TypeError):
            skipped += 1
            continue

        district = TOWN_NAMES.get(town, "")
        full_addr = (
            COUNTY_NAME + district + village_name
            + (neighborhood or "")
            + road
            + (section or "")
            + (lane or "")
            + (alley or "")
            + (number or "")
        )

        record = [
            full_addr, COUNTY_CODE, town, village, neighborhood,
            road, section, lane, alley, "", "", number,
            f"{lon:.15g}", f"{lat:.15g}",
        ]
        road_groups[road or ""].append(record)

        if i % 100_000 == 0:
            print(f"  {i:,} records processed…")

    print(f"  Done — {sum(len(v) for v in road_groups.values()):,} records, {skipped} skipped")

    print(f"Removing old 63-*.csv files…")
    removed = 0
    for f in ROADS_DIR.glob("63-*.csv"):
        f.unlink()
        removed += 1
    print(f"  Removed {removed} files")

    print(f"Writing {len(road_groups)} new road files…")
    for road, records in road_groups.items():
        fname = ROADS_DIR / f"63-{road}.csv"
        with open(fname, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(CSV_HEADER)
            w.writerows(records)

    print(f"Done. {len(road_groups)} road files written to {ROADS_DIR}")


if __name__ == "__main__":
    main()
