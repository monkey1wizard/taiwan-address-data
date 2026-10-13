from __future__ import annotations

import csv
from pathlib import Path
import re
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from update_addresses import (
    COUNTIES,
    FIX_FIELDS,
    apply_char_fixes,
    apply_variants,
    is_private_use,
    load_area,
    load_char_fixes,
    load_rare_chars,
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
    pat = "".join("(.)" if ch == "?" else re.escape(ch) for ch in source)
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
            self.assertEqual(r["standard_codepoint"], f"U+{ord(ch):04X}")
            self.assertEqual(r["block"], _block(ord(ch)), ch)

    def test_each_source_form_maps_to_one_standard_char(self) -> None:
        seen: dict[tuple[str, str], str] = {}
        for r in self.rows:
            key = (r["source"], r["form"])
            self.assertNotIn(key, seen, key)
            seen[key] = r["standard"]
            self.assertIn(r["standard"], self.standard, key)
            self.assertEqual(r["form_codepoints"],
                             " ".join(f"U+{ord(c):04X}" for c in r["form"]))
            self.assertTrue(r["evidence"] and r["checked_on"], key)


class CharFixesTableTest(unittest.TestCase):
    def setUp(self) -> None:
        self.rows = _rows("char_fixes.csv")
        self.standard = {r["standard"] for r in _rows("rare_chars.csv")
                         if r["source"] == "標準"}

    def test_keys_are_unique_and_fields_known(self) -> None:
        keys = [(r["county"], r["town"], r["field"], r["source_value"]) for r in self.rows]
        self.assertEqual(len(keys), len(set(keys)))
        for r in self.rows:
            self.assertIn(r["field"], FIX_FIELDS)
            self.assertTrue(r["evidence"] and r["checked_on"])

    def test_restored_characters_are_in_rare_chars(self) -> None:
        for r in self.rows:
            for ch in _question_chars(r["source_value"], r["fixed_value"]):
                self.assertIn(ch, self.standard, r["fixed_value"])
                self.assertFalse(_in_big5(ch), r["fixed_value"])

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


if __name__ == "__main__":
    unittest.main()
