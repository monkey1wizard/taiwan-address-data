from __future__ import annotations

import io
from pathlib import Path
import sys
import unittest

from openpyxl import Workbook
from pyproj import Transformer


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from update_addresses import COUNTIES, normalize, read_xlsx_rows


def _xlsx_bytes(header: list[str], rows: list[list]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(header)
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


HSINCHU_HEADER = ["省市縣市代碼", "鄉鎮市區代碼", "村里", "鄰", "街或路段", "地區",
                  "巷", "弄", "號", "橫座標", "縱座標"]


class HsinchuSourceTest(unittest.TestCase):
    """新竹縣 reads the XLSX: the government Big5 CSV export writes 號/巷/弄
    as I-/G-/H- and every non-Big5 character as "?"."""

    def test_config_uses_xlsx(self) -> None:
        cfg = COUNTIES["新竹縣"]
        self.assertEqual(cfg.fmt, "xlsx")
        self.assertEqual(cfg.dataset_id, 172380)

    def test_numeric_cells_read_back_without_decimal(self) -> None:
        raw = _xlsx_bytes(HSINCHU_HEADER, [
            [10004, 1000401, "中崙里", 7, "光明九路", None, None, None, "１３９號",
             250873.54, 2746469.84],
        ])
        row = read_xlsx_rows(raw)[0]
        self.assertEqual(row["鄉鎮市區代碼"], "1000401")
        self.assertEqual(row["鄰"], "7")

    def test_leading_ideographic_space_is_stripped(self) -> None:
        raw = _xlsx_bytes(HSINCHU_HEADER, [
            ["10004", "1000401", "中崙里", "5", "光明九路", "", "", "",
             "　　　１０１號二樓", "250873.54", "2746469.84"],
        ])
        row = read_xlsx_rows(raw)[0]
        self.assertEqual(normalize(row["號"]), "101號二樓")

    def test_non_big5_characters_survive(self) -> None:
        raw = _xlsx_bytes(HSINCHU_HEADER, [
            ["10004", "1000402", "上舘里", "1", "犂頭店", "", "", "", "１號",
             "250000", "2740000"],
        ])
        row = read_xlsx_rows(raw)[0]
        self.assertEqual(row["村里"], "上舘里")
        self.assertEqual(row["街或路段"], "犂頭店")
        self.assertNotIn("?", "".join(row.values()))


class CoordinateZoneTest(unittest.TestCase):
    """澎湖 and 金門 publish TWD97 TM2 119° coordinates (EPSG:3825). Every
    other configured county uses the 121° zone (EPSG:3826). A new county
    on another zone must change this test, which forces an explicit choice."""

    ZONE_119 = {"澎湖縣", "金門縣"}

    def test_islands_use_119_zone(self) -> None:
        for name in self.ZONE_119:
            self.assertEqual(COUNTIES[name].epsg, "EPSG:3825", name)

    def test_other_counties_use_121_zone(self) -> None:
        for name, cfg in COUNTIES.items():
            if name not in self.ZONE_119:
                self.assertEqual(cfg.epsg, "EPSG:3826", name)

    def test_source_median_points_land_on_islands(self) -> None:
        cases = {
            "澎湖縣": ((309282, 2607493), (119.58, 23.57)),
            "金門縣": ((182144, 2703818), (118.33, 24.44)),
        }
        for name, ((x, y), (lon, lat)) in cases.items():
            t = Transformer.from_crs(COUNTIES[name].epsg, "EPSG:4326", always_xy=True)
            got_lon, got_lat = t.transform(x, y)
            self.assertAlmostEqual(got_lon, lon, delta=0.01, msg=name)
            self.assertAlmostEqual(got_lat, lat, delta=0.01, msg=name)


if __name__ == "__main__":
    unittest.main()
