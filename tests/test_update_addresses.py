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


class BracketedAndCoordTest(unittest.TestCase):
    def test_single_char_brackets_removed(self) -> None:
        from update_addresses import normalize_bracketed as nb
        self.assertEqual(nb("(塭)南里"), "塭南里")
        self.assertEqual(nb("公(塭)里"), "公塭里")
        self.assertEqual(nb("[萡]子村"), "萡子村")
        self.assertEqual(nb("（塭）南里"), "塭南里")
        self.assertEqual(nb("\U00020000[\U00020001]里"), "\U00020000\U00020001里")

    def test_multi_char_brackets_kept(self) -> None:
        from update_addresses import normalize_bracketed as nb
        for s in ("石[石曹]里", "[木|日]埔村", "(土坂派出所)", "(1)里"):
            self.assertEqual(nb(s), s)

    def test_format_coord(self) -> None:
        from update_addresses import format_coord
        self.assertEqual(format_coord(121.5), "121.500000000")
        self.assertEqual(format_coord(25.0123456789123), "25.012345679")

    def test_source_fields_brackets(self) -> None:
        from update_addresses import source_fields
        col = {"town": "t", "village": "v", "street": "s", "lane": "l",
               "alley": "a", "number": "n"}
        row = {"t": "6500100", "v": "(塭)南里", "s": "公(塭)路", "l": "", "a": "",
               "n": "(土坂派出所)"}
        r = source_fields(row, col, COUNTIES["新北市"], {}, {})
        self.assertEqual(r[1], "塭南里")
        self.assertEqual(r[2], "公塭路")
        self.assertEqual(r[5], "(土坂派出所)")


class LoadAreaTest(unittest.TestCase):
    def test_area_2015_villages(self) -> None:
        import tempfile
        import update_addresses as ua
        with tempfile.TemporaryDirectory() as d:
            a14, a15 = Path(d) / "a14.csv", Path(d) / "a15.csv"
            a14.write_text("name,dgbas_id\n彰化縣員林鎮,1000701\n"
                           "彰化縣員林鎮甲里,1000701-001\n", encoding="utf-8")
            a15.write_text("name,dgbas_id\n彰化縣員林市,1000701\n"
                           "彰化縣員林市甲里,1000701-099\n"
                           "彰化縣員林市乙里,1000701-002\n"
                           "彰化縣員林鎮丙里,1000701-003\n", encoding="utf-8")
            old = ua.AREA_CSV, ua.AREA_2015_CSV
            try:
                ua.AREA_CSV, ua.AREA_2015_CSV = a14, a15
                towns, v = ua.load_area(COUNTIES["彰化縣"])
                self.assertEqual(towns, {"1000701": "員林鎮"})
                self.assertEqual(v[("1000701", "甲里")], "1000701-001")
                self.assertEqual(v[("1000701", "乙里")], "1000701-002")
                self.assertEqual(v[("1000701", "丙里")], "1000701-003")
                ua.AREA_2015_CSV = Path(d) / "missing.csv"
                self.assertNotIn(("1000701", "乙里"), ua.load_area(COUNTIES["彰化縣"])[1])
            finally:
                ua.AREA_CSV, ua.AREA_2015_CSV = old


class SwapCountyFilesTest(unittest.TestCase):
    def test_swap_and_restore(self) -> None:
        import tempfile
        from unittest import mock
        import update_addresses as ua
        rows = [["a"] * len(ua.CSV_HEADER)]
        with tempfile.TemporaryDirectory() as d:
            roads = Path(d)
            (roads / "63-old.csv").write_text("old", encoding="utf-8")
            (roads / "64-keep.csv").write_text("keep", encoding="utf-8")
            (roads / ".staging-63").mkdir()
            (roads / ".staging-63" / "stale.csv").write_text("x")
            ua.swap_county_files(roads, "63", {"new": rows})
            self.assertEqual(sorted(p.name for p in roads.iterdir()),
                             ["63-new.csv", "64-keep.csv"])
            # failure while moving staged files: old files come back
            real = __import__("shutil").move
            calls = {"n": 0}

            def flaky(src, dst):
                calls["n"] += 1
                if calls["n"] == 2:     # first staged file
                    raise OSError("boom")
                return real(src, dst)
            with mock.patch("shutil.move", flaky):
                with self.assertRaises(OSError):
                    ua.swap_county_files(roads, "63", {"x": rows})
            self.assertTrue((roads / "63-new.csv").read_text(encoding="utf-8")
                            .startswith(",".join(ua.CSV_HEADER)))
            self.assertFalse((roads / "63-x.csv").exists())
            self.assertEqual((roads / "64-keep.csv").read_text(), "keep")
