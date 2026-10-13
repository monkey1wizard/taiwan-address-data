from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from update_addresses import CSV_HEADER, _floor_value, dedupe_door_plates


def rec(number: str, x: float = 121.5, y: float = 25.0,
        village: str = "A里", neigh: str = "1鄰") -> list[str]:
    row = dict.fromkeys(CSV_HEADER, "")
    row.update(TOWN="T", VILLAGE=village, NEIGHBORHOOD=neigh, ROAD="路",
               NUMBER=number, X=str(x), Y=str(y))
    return [row[k] for k in CSV_HEADER]


def numbers(rows: list[list[str]]) -> list[str]:
    return [r[CSV_HEADER.index("NUMBER")] for r in rows]


class FloorValueTest(unittest.TestCase):
    def test_values(self):
        for text, want in [("二", 2), ("十", 10), ("十二", 12), ("二十", 20),
                           ("二十三", 23), ("一百", 100), ("３", 3), ("12", 12)]:
            self.assertEqual(_floor_value(text), want, text)


class DedupeTest(unittest.TestCase):
    def test_base_removes_floors(self):
        kept, n = dedupe_door_plates([rec("32號二樓"), rec("32號"), rec("32號二樓之1")])
        self.assertEqual(numbers(kept), ["32號"])
        self.assertEqual(n, 2)

    def test_floors_only_keeps_lowest(self):
        kept, n = dedupe_door_plates([rec("5號三樓"), rec("5號十二樓"), rec("5號二樓")])
        self.assertEqual(numbers(kept), ["5號二樓"])
        self.assertEqual(n, 2)

    def test_numeric_floor_order(self):
        kept, _ = dedupe_door_plates([rec("5號十二樓"), rec("5號二樓")])
        self.assertEqual(numbers(kept), ["5號二樓"])

    def test_sub_number_order(self):
        kept, _ = dedupe_door_plates([rec("5號二樓之2"), rec("5號二樓之1"), rec("5號二樓")])
        self.assertEqual(numbers(kept), ["5號二樓"])
        kept, _ = dedupe_door_plates([rec("5號二樓之2"), rec("5號二樓之1")])
        self.assertEqual(numbers(kept), ["5號二樓之1"])

    def test_distance(self):
        far = 50 / (111320 * 0.9063)  # about 50 m of longitude at lat 25
        near = 5 / (111320 * 0.9063)
        kept, n = dedupe_door_plates([rec("7號"), rec("7號二樓", x=121.5 + far)])
        self.assertEqual((len(kept), n), (2, 0))
        kept, n = dedupe_door_plates([rec("7號"), rec("7號二樓", x=121.5 + near)])
        self.assertEqual((len(kept), n), (1, 1))

    def test_other_group_fields(self):
        _, n = dedupe_door_plates([rec("7號"), rec("7號二樓", village="B里")])
        self.assertEqual(n, 0)
        _, n = dedupe_door_plates([rec("7號"), rec("7號二樓", neigh="2鄰")])
        self.assertEqual(n, 0)

    def test_note_not_grouped_with_base(self):
        kept, n = dedupe_door_plates([rec("107號"), rec("107號(土坂派出所)")])
        self.assertEqual((len(kept), n), (2, 0))

    def test_duplicate_notes(self):
        kept, n = dedupe_door_plates([rec("107號(土坂派出所)"), rec("107號(土坂派出所)")])
        self.assertEqual((len(kept), n), (1, 1))

    def test_fullwidth_digit_floor(self):
        kept, _ = dedupe_door_plates([rec("9號３樓"), rec("9號")])
        self.assertEqual(numbers(kept), ["9號"])
        kept, _ = dedupe_door_plates([rec("9號１２樓"), rec("9號３樓")])
        self.assertEqual(numbers(kept), ["9號３樓"])

    def test_bad_coordinates_kept(self):
        a, b = rec("3號"), rec("3號二樓")
        b[CSV_HEADER.index("X")] = ""
        kept, n = dedupe_door_plates([a, b])
        self.assertEqual((len(kept), n), (2, 0))

    def test_original_order_kept(self):
        rows = [rec("2號", y=25.1), rec("1號二樓"), rec("1號"), rec("3號", y=25.2)]
        kept, _ = dedupe_door_plates(rows)
        self.assertEqual(numbers(kept), ["2號", "1號", "3號"])


if __name__ == "__main__":
    unittest.main()
