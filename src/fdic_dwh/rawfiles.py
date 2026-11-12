"""Canonical raw files: same content, same bytes, same SHA-256 (REC-03)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .contract import DatasetSpec


def canonical_line(row: dict[str, Any]) -> str:
    return json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def row_hash(row: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_line(row).encode("utf-8")).hexdigest()


def sort_rows(spec: DatasetSpec, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(rows, key=spec.sort_key)


def canonical_bytes(rows: list[dict[str, Any]]) -> bytes:
    """JSON Lines with sorted keys and LF endings, independent of page order and OS."""
    return "".join(canonical_line(row) + "\n" for row in rows).encode("utf-8")


def write_raw(
    raw_dir: Path, dataset: str, partition: str, batch_id: str, content: bytes, manifest: dict
) -> tuple[Path, str]:
    target_dir = raw_dir / dataset / partition
    target_dir.mkdir(parents=True, exist_ok=True)
    data_path = target_dir / f"{batch_id}.jsonl"
    data_path.write_bytes(content)
    sha256 = hashlib.sha256(content).hexdigest()
    manifest = {**manifest, "file": data_path.name, "sha256": sha256}
    (target_dir / f"{batch_id}.manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return data_path, sha256
