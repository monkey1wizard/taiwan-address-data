from __future__ import annotations

import csv
import json
from pathlib import Path
import sys
import tempfile
import unittest

import pyarrow as pa
import pyarrow.parquet as pq


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from import_lvr_patch import import_patch
from materialize_addresses import materialize
from supplement_common import (
    ADDRESS_COLUMNS,
    roads_tree_sha256,
    sha256_file,
    write_address_csv,
)


def _write_parquet(path: Path, rows: list[dict], dataset: str, fields: list[tuple[str, pa.DataType]]) -> None:
    schema = pa.schema(fields, metadata={b"lvr.dataset": dataset.encode(), b"lvr.schema_version": b"1.0"})
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), path)


def _snapshot(root: Path, x: str = "121.5") -> Path:
    root.mkdir()
    patch = {
        "patch_id": "patch-1",
        "full_addr": "臺北市中正區幸福里測試路1號",
        "county": "63000",
        "town": "中正區",
        "village": "幸福里",
        "neighborhood": "",
        "road": "測試路",
        "section": "",
        "lane": "",
        "alley": "",
        "sub_alley": "",
        "tong": "",
        "number": "1號",
        "x": x,
        "y": "25.0",
    }
    _write_parquet(
        root / "address_patch.parquet",
        [patch],
        "address-patch",
        [(name, pa.string()) for name in patch],
    )
    provenance = {
        "patch_id": "patch-1",
        "evidence_id": "evidence-1",
        "batch_id": "batch-1",
        "query_fingerprint": "fingerprint-1",
    }
    _write_parquet(
        root / "provenance.parquet",
        [provenance],
        "address-patch-provenance",
        [(name, pa.string()) for name in provenance],
    )
    quarantine_fields = [
        ("candidate_id", pa.string()),
        ("batch_id", pa.string()),
        ("query_fingerprint", pa.string()),
        ("submitted_address", pa.string()),
        ("response_address", pa.string()),
        ("reason", pa.string()),
    ]
    _write_parquet(root / "quarantine.parquet", [], "address-patch-quarantine", quarantine_fields)
    (root / "quality.json").write_text("{}\n", encoding="utf-8")
    artifacts = []
    for name in ["address_patch.parquet", "provenance.parquet", "quarantine.parquet", "quality.json"]:
        path = root / name
        artifacts.append({"path": name, "size_bytes": path.stat().st_size, "sha256": sha256_file(path)})
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "snapshot_id": "synthetic-patch",
                "complete": True,
                "artifacts": artifacts,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return root


def _base_and_supplements(root: Path) -> tuple[Path, Path]:
    base = root / "base"
    roads = base / "roads"
    roads.mkdir(parents=True)
    existing = {name: "" for name in ADDRESS_COLUMNS}
    existing.update(
        {
            "FULL_ADDR": "臺北市中正區幸福里原有路2號",
            "COUNTY": "63000",
            "TOWN": "中正區",
            "VILLAGE": "幸福里",
            "ROAD": "原有路",
            "NUMBER": "2號",
            "X": "121.4",
            "Y": "25.1",
        }
    )
    write_address_csv(roads / "63000-原有路.csv", [existing])
    with (base / "road.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["county_id", "road"])
        writer.writerow(["63000", "原有路"])
    count, digest = roads_tree_sha256(roads)
    supplements = root / "supplements"
    supplements.mkdir()
    (supplements / "legacy-base.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "commit": "synthetic-base",
                "road_file_count": count,
                "roads_tree_sha256": digest,
                "road_index_sha256": sha256_file(base / "road.csv"),
            }
        ),
        encoding="utf-8",
    )
    (supplements / "manifest.json").write_text(
        '{"schema_version":"1.0","legacy_base":"legacy-base.json","sources":[]}\n',
        encoding="utf-8",
    )
    return base, supplements


class SupplementTests(unittest.TestCase):
    def test_import_is_idempotent_and_preserves_legacy_columns(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, supplements = _base_and_supplements(root)
            snapshot = _snapshot(root / "snapshot")
            first = import_patch(snapshot, supplements, "sample")
            second = import_patch(snapshot, supplements, "sample")
            self.assertEqual(first, second)
            with (first / "addresses.csv").open(encoding="utf-8", newline="") as stream:
                self.assertEqual(next(csv.reader(stream)), ADDRESS_COLUMNS)
            manifest = json.loads((supplements / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(len(manifest["sources"]), 1)

    def test_materialization_adds_address_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base, supplements = _base_and_supplements(root)
            import_patch(_snapshot(root / "snapshot"), supplements, "sample")
            output = root / "candidate"
            self.assertEqual(materialize(base, supplements, output), output)
            self.assertEqual(materialize(base, supplements, output), output)
            with (output / "roads" / "63000-測試路.csv").open(encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(rows[0]["FULL_ADDR"], "臺北市中正區幸福里測試路1號")
            manifest = json.loads((output / "materialization-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["address_rows_added"], 1)

    def test_materialization_rejects_conflicting_full_address(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base, supplements = _base_and_supplements(root)
            first = _snapshot(root / "snapshot-a", "121.5")
            import_patch(first, supplements, "first")
            second = _snapshot(root / "snapshot-b", "121.6")
            import_patch(second, supplements, "second")
            output = root / "candidate"
            with self.assertRaisesRegex(ValueError, "conflicts"):
                materialize(base, supplements, output)
            self.assertFalse(output.exists())

    def test_import_rejects_tampered_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, supplements = _base_and_supplements(root)
            snapshot = _snapshot(root / "snapshot")
            with (snapshot / "quality.json").open("a", encoding="utf-8") as stream:
                stream.write("tampered")
            with self.assertRaisesRegex(ValueError, "hash or size differs"):
                import_patch(snapshot, supplements, "sample")


if __name__ == "__main__":
    unittest.main()
