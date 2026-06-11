#!/usr/bin/env python3
"""Probe data.gov.tw / data.nat.gov.tw for each county's door-plate (門牌)
coordinate dataset and build a coverage registry.

Dataset IDs discovered via the platform search UI (2026-06).
Run:  python tools/probe_counties.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import update_taipei as u

COORD_HINTS = ["座標", "坐標", "經度", "緯度", "TWD", "WGS", "x_", "y_", "橫", "縱",
               "雙重", "coordinate", "X", "Y"]

# county -> latest data.gov.tw dataset id (門牌 coordinate family)
IDS = {
    "臺北市": 155472,  # done
    "新北市": 168887,
    "桃園市": 157689,
    "臺中市": 169806,  # done
    "臺南市": 120044,
    "高雄市": 172400,  # 114年 TWD97
    "新竹市": 157547,
    "新竹縣": 172380,
    "苗栗縣": 176511,  # 迄114年12月
    "彰化縣": 170727,
    "雲林縣": 166201,
    "嘉義縣": 172873,
    "屏東縣": 170847,
    "臺東縣": 165619,
    "花蓮縣": 175221,
    "澎湖縣": 170852,
    "金門縣": 171571,
}

# Not found on data.gov.tw search (likely unpublished there): 基隆市, 嘉義市,
# 南投縣, 宜蘭縣, 連江縣.

DOMAINS = ["data.gov.tw", "data.nat.gov.tw"]


def probe(did, s):
    """Try both domains; return parsed metadata from whichever resolves."""
    last = None
    for dom in DOMAINS:
        try:
            r = s.get(f"https://{dom}/api/v2/rest/dataset/{did}", timeout=25)
            if r.status_code == 200 and r.text.strip().startswith("{"):
                res = r.json().get("result")
                if res:
                    res["_domain"] = dom
                    return res
        except Exception as e:
            last = e
    raise RuntimeError(f"no result on either domain ({last})")


def summarize(res):
    dists = res.get("distribution", [])
    fmts = sorted({d.get("resourceFormat", "?") for d in dists})
    fields = {f.get("name", "") for d in dists for f in d.get("resourceField", [])}
    coords = sorted(f for f in fields if any(h in f for h in COORD_HINTS))
    uf = res.get("updateFrequency", {})
    freq = ""
    if isinstance(uf, dict):
        ru = uf.get("regularupdate", "")
        freq = f"{uf.get('Frequency','')}/{uf.get('unittime','')}" if uf.get("Frequency") else f"reg={ru}"
    dl = next((d["resourceDownloadUrl"] for d in dists if d.get("resourceDownloadUrl")), "")
    return fmts, coords, freq, dl, len(dists)


def main():
    s = u._session()
    rows = []
    for name, did in IDS.items():
        try:
            res = probe(did, s)
            fmts, coords, freq, dl, n = summarize(res)
            rows.append((name, did, res.get("title", ""), fmts, coords, freq,
                         res.get("modifiedDate", "")[:10], dl, res["_domain"], n))
        except Exception as e:
            rows.append((name, did, f"ERROR {type(e).__name__}: {e}", [], [], "", "", "", "", 0))

    for (name, did, title, fmts, coords, freq, mod, dl, dom, n) in rows:
        print(f"\n[{name}] {did}  ({dom})")
        print(f"   {title}")
        print(f"   格式={fmts} n={n}  座標欄={coords}")
        print(f"   頻率={freq}  最近更新={mod}")
        print(f"   下載={dl[:96]}")


if __name__ == "__main__":
    main()
