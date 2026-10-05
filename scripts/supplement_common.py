"""Shared validation and deterministic file helpers for address supplements."""

from __future__ import annotations

import csv
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile


ADDRESS_COLUMNS = [
    "FULL_ADDR",
    "COUNTY",
    "TOWN",
    "VILLAGE",
    "NEIGHBORHOOD",
    "ROAD",
    "SECTION",
    "LANE",
    "ALLEY",
    "SUB_ALLEY",
    "TONG",
    "NUMBER",
    "X",
    "Y",
]
PATCH_COLUMNS = [
    "full_addr",
    "county",
    "town",
    "village",
    "neighborhood",
    "road",
    "section",
    "lane",
    "alley",
    "sub_alley",
    "tong",
    "number",
    "x",
    "y",
]
FORBIDDEN = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def sha256_file(path: Path) -> str:
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def canonical_json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def write_json_atomic(path: Path, value) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", newline="\n", dir=path.parent, delete=False
    ) as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2)
        stream.write("\n")
        temporary = Path(stream.name)
    os.replace(temporary, path)


def safe_filename(value: str) -> str:
    if not (value or "").strip():
        return ""
    return FORBIDDEN.sub("_", value).rstrip(" .") or "_"


def read_address_csv(path: Path) -> list[dict]:
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != ADDRESS_COLUMNS:
            raise ValueError(f"Address CSV header differs: {path}")
        return list(reader)


def write_address_csv(path: Path, values: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=ADDRESS_COLUMNS)
        writer.writeheader()
        writer.writerows(values)


def roads_tree_sha256(root: Path) -> tuple[int, str]:
    files = sorted(Path(root).glob("*.csv"), key=lambda path: path.name)
    value = hashlib.sha256()
    for path in files:
        value.update(path.name.encode("utf-8"))
        value.update(b"\0")
        value.update(sha256_file(path).encode("ascii"))
        value.update(b"\n")
    return len(files), value.hexdigest()


def copy_tree(source: Path, target: Path) -> None:
    if target.exists():
        raise FileExistsError(target)
    shutil.copytree(source, target)
