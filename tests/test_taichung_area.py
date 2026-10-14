import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from update_addresses import (
    COUNTIES, _dist_sort_key, apply_char_fixes, parse_drive_confirm,
    parse_taichung_list, source_area,
)

LIST_CSV = (
    "﻿﻿﻿檔案名稱,地圖網址,說明\n"
    "臺中市114年8月GIS門牌號碼,https://drive.google.com/file/d/OLDID/view,a\n"
    "臺中市115年2月GIS門牌號碼,https://drive.google.com/file/d/NEW_id-2/view?usp=x,b\n"
    "臺中市115年1月GIS門牌號碼,https://drive.google.com/file/d/MID/view,c\n"
    "其他資料,https://example.com/x,d\n"
)

CONFIRM_HTML = (
    '<html><body><form id="download-form" action="https://drive.usercontent.'
    'google.com/download" method="get">'
    '<input type="hidden" name="id" value="FID">'
    '<input type="hidden" name="export" value="download">'
    '<input type="hidden" name="confirm" value="t">'
    '<input type="hidden" name="uuid" value="u-1"></form>'
    '<form id="other" action="x"><input name="no" value="1"></form></body></html>'
)


class TaichungTest(unittest.TestCase):
    def test_list_parsing(self) -> None:
        fid, ym, n = parse_taichung_list(LIST_CSV)
        self.assertEqual((fid, ym, n), ("NEW_id-2", (115, 2), 4))

    def test_drive_confirm_form(self) -> None:
        action, params = parse_drive_confirm(CONFIRM_HTML)
        self.assertEqual(action, "https://drive.usercontent.google.com/download")
        self.assertEqual(params, {"id": "FID", "export": "download",
                                  "confirm": "t", "uuid": "u-1"})
        with self.assertRaises(RuntimeError):
            parse_drive_confirm("<html></html>")

    def test_config(self) -> None:
        cfg = COUNTIES["臺中市"]
        self.assertEqual((cfg.code, cfg.epsg, cfg.resolver), ("66", "EPSG:3826", "taichung_drive"))
        self.assertEqual(cfg.columns["x"], "TWD97橫坐標")


class AreaTest(unittest.TestCase):
    COL = {"area": "地區"}

    def merged(self, area: str, lane: str, fixes=None) -> str:
        parts = {"village": "v", "street": "s", "lane": lane, "alley": "", "number": "1號"}
        apply_char_fixes(fixes or {}, "6600100", parts)
        a = source_area({"地區": area}, self.COL, {})
        return a + parts["lane"] if a else parts["lane"]

    def test_area_becomes_lane(self) -> None:
        self.assertEqual(self.merged("十甲巷", ""), "十甲巷")

    def test_area_before_lane(self) -> None:
        self.assertEqual(self.merged("西埔", "3巷"), "西埔3巷")

    def test_char_fix_keyed_on_original_lane(self) -> None:
        fixes = {("6600100", "lane", "3?巷"): "3磘巷"}
        self.assertEqual(self.merged("西埔", "3?巷", fixes), "西埔3磘巷")

    def test_missing_column(self) -> None:
        self.assertEqual(source_area({}, {}, {}), "")
        self.assertEqual(source_area({"x": "1"}, {"area": "地區"}, {}), "")

    def test_brackets_stripped(self) -> None:
        self.assertEqual(source_area({"地區": " (磘)仔 "}, self.COL, {}), "磘仔")


class PlateFixTest(unittest.TestCase):
    def test_plate_village_and_town(self) -> None:
        key = "中山路3巷5號"
        fixes = {("6600100", "plate_village", key): "新里",
                 ("6600100", "plate_town", key): "6600200"}
        parts = {"village": "舊里", "street": "中山路", "lane": "3巷",
                 "alley": "", "number": "5號", "neighborhood": "1鄰"}
        applied = apply_char_fixes(fixes, "6600100", parts)
        self.assertEqual(parts["village"], "新里")
        self.assertEqual(parts["town"], "6600200")
        self.assertIn("plate_village", applied)
        self.assertIn("plate_town", applied)
        # the new code is not used for lookups
        other = dict(parts, village="舊里")
        other.pop("town")
        apply_char_fixes(fixes, "6600200", other)
        self.assertEqual(other["village"], "舊里")
        self.assertNotIn("town", other)


class QualifiedPlateKeyTest(unittest.TestCase):
    """Synthetic fixes only. Keys: village|neighborhood|street+lane+alley+number."""

    def test_qualified_key_needs_matching_village_and_neighborhood(self) -> None:
        fixes = {("6600100", "plate_village", "|6鄰|1號"): "北村"}
        match = {"village": "", "street": "", "lane": "", "alley": "",
                 "number": "1號", "neighborhood": "6鄰"}
        self.assertEqual(apply_char_fixes(fixes, "6600100", match), ["plate_village"])
        self.assertEqual(match["village"], "北村")
        other_village = {"village": "東村", "street": "", "lane": "", "alley": "",
                         "number": "1號", "neighborhood": "6鄰"}
        self.assertEqual(apply_char_fixes(fixes, "6600100", other_village), [])
        self.assertEqual(other_village["village"], "東村")
        other_nei = {"village": "", "street": "", "lane": "", "alley": "",
                     "number": "1號", "neighborhood": "7鄰"}
        self.assertEqual(apply_char_fixes(fixes, "6600100", other_nei), [])
        self.assertEqual(other_nei["village"], "")

    def test_tail_key_applies_regardless_of_village_and_neighborhood(self) -> None:
        fixes = {("6600100", "plate_village", "信義路41號"): "新里"}
        for village, nei in (("", ""), ("東村", "3鄰")):
            parts = {"village": village, "street": "信義路", "lane": "", "alley": "",
                     "number": "41號", "neighborhood": nei}
            self.assertEqual(apply_char_fixes(fixes, "6600100", parts), ["plate_village"])
            self.assertEqual(parts["village"], "新里")

    def test_plate_street_qualified_key(self) -> None:
        fixes = {("6600100", "plate_street", "||65號"): "嘉和路"}
        parts = {"village": "", "street": "", "lane": "", "alley": "",
                 "number": "65號", "neighborhood": ""}
        applied = apply_char_fixes(fixes, "6600100", parts)
        self.assertEqual(parts["street"], "嘉和路")
        self.assertIn("plate_street", applied)

    def test_full_key_wins_over_tail_key(self) -> None:
        fixes = {("6600100", "plate_street", "信義路41號"): "甲路",
                 ("6600100", "plate_street", "|6鄰|信義路41號"): "乙路"}
        parts = {"village": "", "street": "信義路", "lane": "", "alley": "",
                 "number": "41號", "neighborhood": "6鄰"}
        applied = apply_char_fixes(fixes, "6600100", parts)
        self.assertEqual(parts["street"], "乙路")
        self.assertEqual(applied.count("plate_street"), 1)
        # Without the qualifying neighborhood, the tail key applies.
        plain = {"village": "", "street": "信義路", "lane": "", "alley": "",
                 "number": "41號", "neighborhood": "7鄰"}
        apply_char_fixes(fixes, "6600100", plain)
        self.assertEqual(plain["street"], "甲路")


class SortKeyTest(unittest.TestCase):
    def test_tainan_year_only(self) -> None:
        self.assertGreater(_dist_sort_key({"resourceDescription": "114年臺南市門牌坐標資料"}),
                           _dist_sort_key({"resourceDescription": "113年臺南市門牌坐標資料"}))
        self.assertEqual(COUNTIES["臺南市"].pick, "latest")

    def test_kaohsiung_year_month(self) -> None:
        self.assertLess(_dist_sort_key({"resourceDescription": "114年8月門牌坐標資料"}),
                        _dist_sort_key({"resourceDescription": "114年12月門牌坐標資料"}))


if __name__ == "__main__":
    unittest.main()


class PlateAreaTest(unittest.TestCase):
    def test_plate_area_sets_area(self) -> None:
        from update_addresses import apply_char_fixes
        fixes = {("1001325", "plate_area", "||65號"): ""}
        parts = {"village": "", "street": "", "lane": "", "alley": "",
                 "number": "65號", "neighborhood": ""}
        self.assertIn("plate_area", apply_char_fixes(fixes, "1001325", parts))
        self.assertEqual(parts["area"], "")

