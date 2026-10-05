#!/usr/bin/env python3
"""Import an immutable taiwan-lvr-geodata address-patch snapshot."""

from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path
import shutil

import pyarrow.parquet as pq

from supplement_common import (
    PATCH_COLUMNS,
    canonical_json,
    sha256_file,
    write_address_csv,
    write_json_atomic,
)


def _manifest(path: Path) -> dict:
    value = json.loads((Path(path) / "manifest.json").read_text(encoding="utf-8"))
    if value.get("schema_version") != "1.0" or value.get("complete") is not True:
        raise ValueError("Patch snapshot is incomplete or unsupported")
    artifacts = {item["path"]: item for item in value.get("artifacts", [])}
    required = {"address_patch.parquet", "provenance.parquet", "quarantine.parquet", "quality.json"}
    if not required.issubset(artifacts):
        raise ValueError("Patch snapshot artifacts missing")
    for name, item in artifacts.items():
        file = Path(path) / name
        if not file.is_file() or file.stat().st_size != item["size_bytes"] or sha256_file(file) != item["sha256"]:
            raise ValueError(f"Patch artifact hash or size differs: {name}")
    return value


def _parquet(path: Path, dataset: str) -> list[dict]:
    file = pq.ParquetFile(path)
    metadata = file.schema_arrow.metadata or {}
    if metadata.get(b"lvr.dataset") != dataset.encode() or metadata.get(b"lvr.schema_version") != b"1.0":
        raise ValueError(f"Unexpected Parquet contract: {path.name}")
    return file.read().to_pylist()


def import_patch(snapshot: Path, supplements: Path, source_id: str) -> Path:
    if not source_id or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for char in source_id):
        raise ValueError("Unsafe supplement source ID")
    snapshot = Path(snapshot).resolve()
    supplements = Path(supplements).resolve()
    source_manifest = _manifest(snapshot)
    source_manifest_sha256 = sha256_file(snapshot / "manifest.json")
    root_manifest_path = supplements / "manifest.json"
    root_manifest = json.loads(root_manifest_path.read_text(encoding="utf-8"))
    if root_manifest.get("schema_version") != "1.0" or not isinstance(root_manifest.get("sources"), list):
        raise ValueError("Unsupported supplements manifest")
    target = supplements / "lvr" / source_id
    existing = next((row for row in root_manifest["sources"] if row["source_id"] == source_id), None)
    if existing:
        if existing["source_manifest_sha256"] != source_manifest_sha256 or not target.is_dir():
            raise ValueError("Existing supplement source differs")
        return target
    if target.exists():
        raise ValueError("Unindexed supplement directory exists")

    lock = supplements / ".import-lock"
    try:
        lock.mkdir()
    except FileExistsError as exc:
        raise RuntimeError("Supplement importer busy or stale lock") from exc
    stage = supplements / ".staging" / source_id
    try:
        if stage.exists():
            raise RuntimeError("Interrupted supplement staging requires review")
        stage.mkdir(parents=True)
        patch_rows = _parquet(snapshot / "address_patch.parquet", "address-patch")
        provenance = _parquet(snapshot / "provenance.parquet", "address-patch-provenance")
        quarantined = _parquet(snapshot / "quarantine.parquet", "address-patch-quarantine")
        patch_ids = {row["patch_id"] for row in patch_rows}
        if len(patch_ids) != len(patch_rows):
            raise ValueError("Duplicate patch ID")
        provenance_patch_ids = {row["patch_id"] for row in provenance}
        if provenance_patch_ids - patch_ids:
            raise ValueError("Provenance refers to an absent patch")
        if patch_ids - provenance_patch_ids:
            raise ValueError("Patch lacks provenance")

        addresses = []
        for row in patch_rows:
            if set(PATCH_COLUMNS) - set(row):
                raise ValueError("Patch lacks 14-column values")
            value = {key.upper(): row[key] for key in PATCH_COLUMNS}
            value["X"], value["Y"] = str(row["x"]), str(row["y"])
            if not all(value[key] for key in ["FULL_ADDR", "COUNTY", "TOWN", "VILLAGE", "NUMBER", "X", "Y"]):
                raise ValueError("Patch lacks required address evidence")
            addresses.append(value)
        addresses.sort(key=lambda row: (row["COUNTY"], row["ROAD"], row["FULL_ADDR"], row["X"], row["Y"]))
        write_address_csv(stage / "addresses.csv", addresses)
        with (stage / "provenance.jsonl").open("w", encoding="utf-8", newline="\n") as stream:
            for row in sorted(provenance, key=lambda value: (value["patch_id"], value["evidence_id"])):
                stream.write(canonical_json(row) + "\n")
        with (stage / "quarantine.csv").open("w", encoding="utf-8", newline="") as stream:
            fields = ["candidate_id", "batch_id", "query_fingerprint", "submitted_address", "response_address", "reason"]
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(sorted(quarantined, key=lambda row: row["candidate_id"]))
        imported_manifest = {
            "schema_version": "1.0",
            "source_id": source_id,
            "source_snapshot_id": source_manifest["snapshot_id"],
            "source_manifest_sha256": source_manifest_sha256,
            "address_rows": len(addresses),
            "provenance_rows": len(provenance),
            "quarantine_rows": len(quarantined),
            "artifacts": {
                name: {"sha256": sha256_file(stage / name), "size_bytes": (stage / name).stat().st_size}
                for name in ["addresses.csv", "provenance.jsonl", "quarantine.csv"]
            },
        }
        write_json_atomic(stage / "manifest.json", imported_manifest)
        import_manifest_sha256 = sha256_file(stage / "manifest.json")
        target.parent.mkdir(parents=True, exist_ok=True)
        root_manifest["sources"].append({
            "source_id": source_id,
            "path": f"lvr/{source_id}",
            "source_manifest_sha256": source_manifest_sha256,
            "import_manifest_sha256": import_manifest_sha256,
        })
        root_manifest["sources"].sort(key=lambda row: row["source_id"])
        os.rename(stage, target)
        try:
            write_json_atomic(root_manifest_path, root_manifest)
        except Exception:
            shutil.rmtree(target)
            raise
        return target
    except Exception:
        if stage.exists():
            shutil.rmtree(stage)
        raise
    finally:
        lock.rmdir()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--supplements", type=Path, default=Path("supplements"))
    parser.add_argument("--source-id", required=True)
    args = parser.parse_args()
    path = import_patch(args.snapshot, args.supplements, args.source_id)
    print(json.dumps({"path": str(path), "completed": True}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
