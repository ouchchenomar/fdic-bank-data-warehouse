"""Batch report: what was extracted, rejected, loaded or refused, and why."""

from __future__ import annotations

import psycopg

_COLUMNS = [
    ("batch_id", 40),
    ("status", 9),
    ("mode", 9),
    ("rows_announced", 9),
    ("rows_extracted", 9),
    ("rows_rejected", 8),
    ("rows_loaded", 8),
    ("sha256", 12),
    ("source_index_name", 30),
]

_HEADERS = {
    "rows_announced": "announced",
    "rows_extracted": "extracted",
    "rows_rejected": "rejected",
    "rows_loaded": "loaded",
    "sha256": "sha256",
    "source_index_name": "source index",
}


def _cell(value, width: int) -> str:
    text = "" if value is None else str(value)
    return text[:width].ljust(width)


def batch_report(conn: psycopg.Connection, limit: int = 30, dataset: str | None = None) -> str:
    rows = conn.execute(
        "select batch_id, status, mode, rows_announced, rows_extracted, rows_rejected,"
        " rows_loaded, left(file_sha256, 12), source_index_name, error, duplicate_of"
        " from ops.batch where %(dataset)s::text is null or dataset = %(dataset)s"
        " order by started_at desc, batch_id desc limit %(limit)s",
        {"dataset": dataset, "limit": limit},
    ).fetchall()
    lines = ["  ".join(_cell(_HEADERS.get(name, name), width) for name, width in _COLUMNS)]
    lines.append("  ".join("-" * width for _, width in _COLUMNS))
    for row in rows:
        lines.append("  ".join(_cell(value, width)
                               for value, (_, width) in zip(row[:9], _COLUMNS, strict=True)))
        error, duplicate_of = row[9], row[10]
        if duplicate_of:
            lines.append(f"    same file as {duplicate_of}: nothing loaded")
        if error:
            shown = error if len(error) <= 200 else error[:200] + " [...]"
            lines.append(f"    error: {shown}")
    return "\n".join(lines)
