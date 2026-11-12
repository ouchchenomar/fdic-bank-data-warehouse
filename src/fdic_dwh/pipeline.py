"""One ingestion run: extract, archive, validate, then load or refuse (DWH-01, DWH-02, REC-03)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import psycopg

from . import registry
from .config import ROOT
from .contract import DatasetSpec, validate_rows
from .db import load_rows
from .rawfiles import canonical_bytes, sort_rows, write_raw
from .sources import Source


@dataclass(frozen=True)
class Outcome:
    batch_id: str
    dataset: str
    partition: str
    status: str
    rows_announced: int | None
    rows_extracted: int | None
    rows_rejected: int | None
    rows_loaded: int | None
    duplicate_of: str | None
    error: str | None


def make_batch_id(dataset: str, partition: str, when: datetime) -> str:
    return f"{dataset}_{partition}_{when:%Y%m%dT%H%M%S}{when.microsecond // 1000:03d}Z"


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _finish(conn: psycopg.Connection, batch_id: str, **fields) -> Outcome:
    registry.update_batch(conn, batch_id, finished_at=datetime.now(UTC), **fields)
    conn.commit()
    row = registry.get_batch(conn, batch_id)
    return Outcome(
        batch_id=batch_id,
        dataset=row["dataset"],
        partition=row["partition_value"],
        status=row["status"],
        rows_announced=row["rows_announced"],
        rows_extracted=row["rows_extracted"],
        rows_rejected=row["rows_rejected"],
        rows_loaded=row["rows_loaded"],
        duplicate_of=row["duplicate_of"],
        error=row["error"],
    )


def ingest(
    conn: psycopg.Connection,
    spec: DatasetSpec,
    source: Source,
    raw_dir: Path,
    partition: str | None = None,
) -> Outcome:
    label = partition or "all"
    started = datetime.now(UTC)
    batch_id = make_batch_id(spec.name, label, started)
    registry.create_batch(conn, batch_id=batch_id, dataset=spec.name, partition=label,
                          mode=source.mode)
    conn.commit()

    try:
        fetched = source.fetch(spec, partition)
        rows = sort_rows(spec, fetched.rows)
        validation = validate_rows(spec, rows)
        content = canonical_bytes(rows)
        manifest = {
            "batch_id": batch_id,
            "dataset": spec.name,
            "partition": label,
            "mode": source.mode,
            "extracted_at": started.isoformat(),
            "request_url": fetched.request_url,
            "request_params": fetched.request_params,
            "source_index_name": fetched.index_name,
            "source_index_created_at": fetched.index_created_at,
            "pages": fetched.pages,
            "rows_announced": fetched.rows_announced,
            "rows_extracted": len(rows),
        }
        path, sha256 = write_raw(raw_dir, spec.name, label, batch_id, content, manifest)
        registry.update_batch(
            conn,
            batch_id,
            status="extracted",
            request_url=fetched.request_url,
            request_params=fetched.request_params,
            source_index_name=fetched.index_name,
            source_index_created_at=_parse_ts(fetched.index_created_at),
            pages=fetched.pages,
            rows_announced=fetched.rows_announced,
            rows_extracted=len(rows),
            rows_rejected=len(validation.rejected_rows),
            file_path=_relative(path),
            file_sha256=sha256,
        )
        registry.add_rejects(conn, batch_id, validation.rejects)
        conn.commit()

        errors = []
        if not rows and fetched.rows_announced == 0:
            errors.append("the source announces 0 rows for this partition (not published yet?)")
        if len(rows) != fetched.rows_announced:
            errors.append(
                f"coverage: {len(rows)} rows extracted for {fetched.rows_announced} announced"
            )
        errors += [e for e in validation.blocking_errors(spec.max_reject_rate)
                   if not (e == "no rows extracted" and errors)]
        if errors:
            return _finish(conn, batch_id, status="failed", error="; ".join(errors))

        previous = registry.latest_loaded(conn, spec.name, label)
        if previous and previous[1] == sha256:
            # Same bytes as the last loaded batch: trace the attempt, load nothing.
            return _finish(conn, batch_id, status="duplicate", duplicate_of=previous[0],
                           rows_loaded=0)

        rejected = validation.rejected_rows
        kept = [row for number, row in enumerate(rows, start=1) if number not in rejected]
        loaded = load_rows(conn, spec, batch_id, kept)
        # Rows and status are committed together: a batch is never half loaded.
        return _finish(conn, batch_id, status="loaded", rows_loaded=loaded)
    except Exception as exc:  # noqa: BLE001 - every failure must reach the register
        conn.rollback()
        return _finish(conn, batch_id, status="failed", error=f"{type(exc).__name__}: {exc}"[:2000])
