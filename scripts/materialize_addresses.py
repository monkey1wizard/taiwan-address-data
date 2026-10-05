#!/usr/bin/env python3
"""Materialize legacy roads plus reviewed supplements into an isolated candidate."""

from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path
import shutil

from supplement_common import (
    copy_tree,
    read_address_csv,
    roads_tree_sha256,
    safe_filename,
    sha256_file,
    write_address_csv,
    write_json_atomic,
)


def _verify_base(base: Path, descriptor: dict) -> None:
    count, digest = roads_tree_sha256(Path(base) / "roads")
    if count != descriptor["road_file_count"] or digest != descriptor["roads_tree_sha256"]:
        raise ValueError("Legacy base roads differ from pinned manifest")
    if sha256_file(Path(base) / "road.csv") != descriptor["road_index_sha256"]:
        raise ValueError("Legacy base road.csv differs from pinned manifest")


def _write_road_index(roads: Path, output: Path) -> None:
    entries = []
    seen = set()
    for path in sorted(roads.glob("*.csv"), key=lambda item: item.name):
        parts = path.stem.split("-", 1)
        if len(parts) != 2:
            continue
        key = (parts[0], parts[1])
        if key not in seen:
            seen.add(key)
            entries.append(key)
    with output.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["county_id", "road"])
        writer.writerows(entries)


def materialize(base: Path, supplements: Path, output: Path) -> Path:
    base, supplements, output = Path(base).resolve(), Path(supplements).resolve(), Path(output).resolve()
    descriptor = json.loads((supplements / "legacy-base.json").read_text(encoding="utf-8"))
    root_manifest = json.loads((supplements / "manifest.json").read_text(encoding="utf-8"))
    if root_manifest.get("schema_version") != "1.0" or not isinstance(root_manifest.get("sources"), list):
        raise ValueError("Unsupported supplements manifest")
    _verify_base(base, descriptor)
    supplement_manifest_sha256 = sha256_file(supplements / "manifest.json")
    if output.exists():
        manifest = json.loads((output / "materialization-manifest.json").read_text(encoding="utf-8"))
        if manifest["supplement_manifest_sha256"] != supplement_manifest_sha256:
            raise ValueError("Existing materialization uses different supplements")
        return output

    stage = output.parent / f".{output.name}.staging"
    if stage.exists():
        raise RuntimeError("Interrupted materialization requires review")
    stage.mkdir(parents=True)
    try:
        copy_tree(base / "roads", stage / "roads")
        grouped = {}
        source_manifests = []
        for source in root_manifest["sources"]:
            source_root = supplements / source["path"]
            if sha256_file(source_root / "manifest.json") != source["import_manifest_sha256"]:
                raise ValueError("Imported supplement manifest differs")
            imported = json.loads((source_root / "manifest.json").read_text(encoding="utf-8"))
            for name, expected in imported.get("artifacts", {}).items():
                artifact = source_root / name
                if (
                    not artifact.is_file()
                    or artifact.stat().st_size != expected["size_bytes"]
                    or sha256_file(artifact) != expected["sha256"]
                ):
                    raise ValueError(f"Imported supplement artifact differs: {name}")
            source_manifests.append(source["import_manifest_sha256"])
            for row in read_address_csv(source_root / "addresses.csv"):
                grouped.setdefault((row["COUNTY"], row["ROAD"]), []).append(row)

        added = duplicate = 0
        for (county, road), incoming in sorted(grouped.items()):
            target = stage / "roads" / f"{county}-{safe_filename(road)}.csv"
            current = read_address_csv(target) if target.exists() else []
            by_address = {row["FULL_ADDR"]: row for row in current}
            if len(by_address) != len(current):
                raise ValueError(f"Legacy base has duplicate FULL_ADDR: {target.name}")
            for row in incoming:
                previous = by_address.get(row["FULL_ADDR"])
                if previous is None:
                    by_address[row["FULL_ADDR"]] = row
                    added += 1
                elif previous == row:
                    duplicate += 1
                else:
                    raise ValueError(f"Supplement conflicts with existing address: {row['FULL_ADDR']}")
            write_address_csv(target, sorted(by_address.values(), key=lambda row: row["FULL_ADDR"]))
        _write_road_index(stage / "roads", stage / "road.csv")
        count, tree_hash = roads_tree_sha256(stage / "roads")
        manifest = {
            "schema_version": "1.0",
            "legacy_base_commit": descriptor["commit"],
            "legacy_base_roads_tree_sha256": descriptor["roads_tree_sha256"],
            "supplement_manifest_sha256": supplement_manifest_sha256,
            "source_manifest_sha256": source_manifests,
            "address_rows_added": added,
            "duplicate_rows_ignored": duplicate,
            "road_file_count": count,
            "roads_tree_sha256": tree_hash,
            "road_index_sha256": sha256_file(stage / "road.csv"),
        }
        write_json_atomic(stage / "materialization-manifest.json", manifest)
        os.rename(stage, output)
        return output
    except Exception:
        if stage.exists():
            shutil.rmtree(stage)
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", type=Path, default=Path("."))
    parser.add_argument("--supplements", type=Path, default=Path("supplements"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    path = materialize(args.base, args.supplements, args.output)
    print(json.dumps({"path": str(path), "completed": True}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
