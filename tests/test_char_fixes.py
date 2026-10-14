from __future__ import annotations

import csv
from pathlib import Path
import re
import sys
import tempfile
import unicodedata
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from fix_static_roads import fix_row
from update_addresses import (
    COUNTIES,
    FIX_FIELDS,
    apply_char_fixes,
    apply_variants,
    is_private_use,
    load_area,
    load_char_fixes,
    load_rare_chars,
    source_fields,
)


def _rows(name: str) -> list[dict]:
    with open(ROOT / name, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _block(cp: int) -> str:
    if 0x4E00 <= cp <= 0x9FFF:
        return "基本區"
    if 0x3400 <= cp <= 0x4DBF:
        return "擴充 A"
    if 0x20000 <= cp <= 0x2A6DF:
        return "擴充 B"
    if 0x2A700 <= cp <= 0x2EBEF:
        return "擴充 C 至 F"
    if 0x30000 <= cp <= 0x323AF:
        return "擴充 G 至 H"
    if 0xF900 <= cp <= 0xFAFF or 0x2F800 <= cp <= 0x2FA1F:
        return "相容區"
    return "其他"


def _in_big5(ch: str) -> bool:
    try:
        ch.encode("cp950")
        return True
    except UnicodeEncodeError:
        return False


def _question_chars(source: str, fixed: str) -> tuple[str, ...]:
    pat = "".join("(.)" if ch in "?■？" else re.escape(ch) for ch in source)
    m = re.fullmatch(pat, fixed)
    if m is None:
        raise AssertionError(f"{fixed!r} does not keep the known parts of {source!r}")
    return m.groups()


class RareCharsTableTest(unittest.TestCase):
    """rare_chars.csv is the code-point authority for characters that the
    government exports lose as "?". It does not restore "?" by itself."""

    def setUp(self) -> None:
        self.rows = _rows("rare_chars.csv")
        self.standard = {r["standard"] for r in self.rows if r["source"] == "標準"}

    def test_standard_rows_are_non_big5_standard_unicode(self) -> None:
        for r in self.rows:
            if r["source"] != "標準":
                continue
            ch = r["standard"]
            self.assertEqual(r["form"], ch)
            self.assertFalse(_in_big5(ch), ch)
            self.assertFalse(is_private_use(ch), ch)
            self.assertEqual(unicodedata.normalize("NFC", ch), ch)
            self.assertEqual(r["standard_codepoint"], f"U+{ord(ch):04X}")
            self.assertEqual(r["block"], _block(ord(ch)), ch)

    def test_each_source_form_maps_to_one_standard_char(self) -> None:
        seen: dict[tuple[str, str], str] = {}
        for r in self.rows:
            key = (r["source"], r["form"])
            self.assertNotIn(key, seen, key)
            seen[key] = r["standard"]
            compat = unicodedata.normalize("NFC", r["form"]) == r["standard"] != r["form"]
            if not compat:
                self.assertIn(r["standard"], self.standard, key)
            self.assertEqual(r["form_codepoints"],
                             " ".join(f"U+{ord(c):04X}" for c in r["form"]))
            self.assertTrue(r["evidence"] and r["checked_on"], key)


class CharFixesTableTest(unittest.TestCase):
    def setUp(self) -> None:
        self.rows = _rows("char_fixes.csv")
        rare = _rows("rare_chars.csv")
        self.standard = {r["standard"] for r in rare if r["source"] == "標準"}
        # Big5 characters whose official spelling is a compatibility
        # ideograph. The export cannot encode that code point either.
        self.compat = {r["standard"] for r in rare if r["source"] != "標準"
                       and unicodedata.normalize("NFC", r["form"]) == r["standard"]}

    def test_keys_are_unique_and_fields_known(self) -> None:
        keys = [(r["county"], r["town"], r["field"], r["source_value"]) for r in self.rows]
        self.assertEqual(len(keys), len(set(keys)))
        for r in self.rows:
            # "full_addr" is only applied by fix_static_roads.py.
            self.assertIn(r["field"], FIX_FIELDS + ("full_addr", "number", "neighborhood", "drop", "plate_area",
                                             "plate_village", "plate_town", "plate_street", "area"))
            self.assertTrue(r["evidence"] and r["checked_on"])

    def test_restored_characters_are_in_rare_chars(self) -> None:
        for r in self.rows:
            if r["field"] in ("plate_town", "drop", "neighborhood", "plate_street", "plate_village", "plate_area"):
                continue  # codes or row removal, not text with filled-in characters
            if "改寫" in r["evidence"]:
                # The value was rewritten, not only a lost character filled in.
                self.assertFalse(any(is_private_use(c) for c in r["fixed_value"]))
                continue
            marks = [c for c in r["source_value"] if c in "?■？"]
            for ch, mark in zip(_question_chars(r["source_value"], r["fixed_value"]), marks):
                self.assertFalse(is_private_use(ch), r["fixed_value"])
                if ch in self.compat:
                    continue
                if mark == "?" and "擁有者確認" not in r["evidence"]:
                    # "?" comes from a Big5 export, so the lost character is outside Big5.
                    # Values the owner confirmed by hand may break this rule.
                    self.assertFalse(_in_big5(ch), r["fixed_value"])
                if not _in_big5(ch):
                    self.assertIn(ch, self.standard, r["fixed_value"])

    def test_restored_villages_have_area_codes(self) -> None:
        by_code = {cfg.code: cfg for cfg in COUNTIES.values()}
        areas: dict[str, dict] = {}
        for r in self.rows:
            if r["field"] != "village":
                continue
            if r["county"] not in areas:
                areas[r["county"]] = load_area(by_code[r["county"]])[1]
            self.assertIn((r["town"], r["fixed_value"]), areas[r["county"]], r)

    def test_south_yao_village_resolves(self) -> None:
        villages = load_area(COUNTIES["彰化縣"])[1]
        self.assertEqual(villages[("1000701", "南瑶里")], "1000701-039")


class ApplyFixesTest(unittest.TestCase):
    """Synthetic tables only. Nothing here reads the network."""

    def _write(self, d: Path, name: str, header: list[str], rows: list[list[str]]) -> Path:
        path = d / name
        with open(path, "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(header)
            w.writerows(rows)
        return path

    def test_private_use_form_applies_only_to_its_source(self) -> None:
        pua = "\U000FFFA8"
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(Path(tmp), "rare.csv",
                               ["source", "form", "form_codepoints", "standard",
                                "standard_codepoint", "block", "evidence", "checked_on"],
                               [["10013", pua, "U+FFFA8", "磘", "U+78D8", "基本區", "x", "d"]])
            rare = load_rare_chars(path)
        self.assertEqual(apply_variants(f"瓦{pua}路", rare.get("10013", {})), "瓦磘路")
        self.assertEqual(apply_variants(f"瓦{pua}路", rare.get("10007", {})), f"瓦{pua}路")

    def test_same_value_in_different_towns_is_fixed_separately(self) -> None:
        header = ["county", "town", "field", "source_value", "fixed_value",
                  "evidence", "checked_on"]
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(Path(tmp), "fixes.csv", header, [
                ["10013", "1001321", "street", "?光路", "羗光路", "x", "d"],
                ["10013", "1001317", "street", "?光路", "塩光路", "x", "d"],
                ["10007", "1001321", "street", "?光路", "錯誤路", "x", "d"],
            ])
            fixes = load_char_fixes("10013", path)
        a = {"village": "", "street": "?光路", "lane": ""}
        b = {"village": "", "street": "?光路", "lane": ""}
        self.assertEqual(apply_char_fixes(fixes, "1001321", a), ["street"])
        self.assertEqual(apply_char_fixes(fixes, "1001317", b), ["street"])
        self.assertEqual(a["street"], "羗光路")
        self.assertEqual(b["street"], "塩光路")

    def test_unlisted_value_keeps_question_mark(self) -> None:
        parts = {"village": "", "street": "上林路頂?段", "lane": "田?巷"}
        self.assertEqual(apply_char_fixes({}, "1000723", parts), [])
        self.assertEqual(parts["street"], "上林路頂?段")
        self.assertEqual(parts["lane"], "田?巷")

    def test_fixed_village_finds_its_code(self) -> None:
        villages = load_area(COUNTIES["彰化縣"])[1]
        fixes = load_char_fixes("10007")
        parts = {"village": "下?里", "street": "", "lane": ""}
        apply_char_fixes(fixes, "1000701", parts)
        self.assertEqual(parts["village"], "下廍里")
        self.assertIn(("1000701", parts["village"]), villages)


class NormalizeAndStaticFixTest(unittest.TestCase):
    def test_source_fields_normalize_compatibility_ideographs(self) -> None:
        cfg = COUNTIES["桃園市"]
        col = dict(cfg.columns)
        row = {col["town"]: "6800100", col["village"]: "明德里", col["street"]: "中寧街",
               col["lane"]: "", col["alley"]: "", col["number"]: "１號"}
        _, _, street, _, _, number = source_fields(row, col, cfg, {}, {})
        self.assertEqual(street, "中寧街")
        self.assertEqual(number, "1號")

    def test_static_row_fix_updates_road_section_lane_and_full_address(self) -> None:
        fixes = {("1000206", "street", "?後路仁愛新村"): "廍後路仁愛新村",
                 ("1000212", "lane", "?泉巷"): "温泉巷"}
        row = {"FULL_ADDR": "宜蘭縣壯圍鄉美城村1鄰?後路仁愛新村5號", "TOWN": "1000206",
               "ROAD": "?後路仁愛新村", "SECTION": "", "LANE": "", "ALLEY": "", "NUMBER": "5號"}
        self.assertTrue(fix_row(row, fixes, {}))
        self.assertEqual(row["ROAD"], "廍後路仁愛新村")
        self.assertEqual(row["FULL_ADDR"], "宜蘭縣壯圍鄉美城村1鄰廍後路仁愛新村5號")
        lane = {"FULL_ADDR": "宜蘭縣南澳鄉武塔村6鄰新溪路?泉巷2號", "TOWN": "1000212",
                "ROAD": "新溪路", "SECTION": "", "LANE": "?泉巷", "ALLEY": "", "NUMBER": "2號"}
        self.assertTrue(fix_row(lane, fixes, {}))
        self.assertEqual(lane["FULL_ADDR"], "宜蘭縣南澳鄉武塔村6鄰新溪路温泉巷2號")
        untouched = dict(lane, LANE="田?巷", FULL_ADDR="x田?巷")
        self.assertFalse(fix_row(untouched, fixes, {}))

    def test_number_fix_is_tied_to_one_door_plate(self) -> None:
        fixes = {("6500100", "number", "重慶路93巷32號二■"): "重慶路93巷32號二樓"}
        same = {"village": "", "street": "重慶路", "lane": "93巷", "alley": "", "number": "32號二■"}
        other = {"village": "", "street": "文化路", "lane": "", "alley": "", "number": "32號二■"}
        self.assertEqual(apply_char_fixes(fixes, "6500100", same), ["number"])
        self.assertEqual(same["number"], "32號二樓")
        self.assertEqual(apply_char_fixes(fixes, "6500100", other), [])
        self.assertEqual(other["number"], "32號二■")
        row = {"FULL_ADDR": "新北市板橋區後埔里8鄰重慶路93巷32號二■", "TOWN": "6500100",
               "ROAD": "重慶路", "SECTION": "", "LANE": "93巷", "ALLEY": "", "NUMBER": "32號二■"}
        self.assertTrue(fix_row(row, fixes, {}))
        self.assertEqual(row["FULL_ADDR"], "新北市板橋區後埔里8鄰重慶路93巷32號二樓")

    def test_neighborhood_fix_uses_the_source_number(self) -> None:
        fixes = {("0902001", "neighborhood", "珠浦東路36?1號"): "4鄰",
                 ("0902001", "number", "珠浦東路36?1號"): "珠浦東路36號之2"}
        parts = {"village": "東門里", "street": "珠浦東路", "lane": "", "alley": "",
                 "number": "36?1號", "neighborhood": "25鄰"}
        self.assertEqual(sorted(apply_char_fixes(fixes, "0902001", parts)),
                         ["neighborhood", "number"])
        self.assertEqual((parts["neighborhood"], parts["number"]), ("4鄰", "36號之2"))

    def test_drop_fix_marks_one_door_plate(self) -> None:
        fixes = {("6502100", "drop", "43之7號■樓"): ""}
        row = {"village": "店子里", "street": "", "lane": "", "alley": "", "number": "43之7號■樓"}
        keep = dict(row, number="43之7號")
        self.assertIn("drop", apply_char_fixes(fixes, "6502100", row))
        self.assertNotIn("drop", apply_char_fixes(fixes, "6502100", keep))

    def test_static_full_address_fix_leaves_columns(self) -> None:
        fixes = {("6601400", "full_addr", "文明■"): "文明街"}
        row = {"FULL_ADDR": "臺中市梧棲區大村里24鄰文明■294號", "TOWN": "6601400",
               "ROAD": "", "SECTION": "", "LANE": "", "ALLEY": "", "NUMBER": "294號"}
        self.assertTrue(fix_row(row, fixes, {}))
        self.assertEqual(row["FULL_ADDR"], "臺中市梧棲區大村里24鄰文明街294號")
        self.assertEqual(row["ROAD"], "")


if __name__ == "__main__":
    unittest.main()
