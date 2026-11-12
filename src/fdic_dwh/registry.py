"""Batch register (ops.batch): one row per extraction attempt."""

from __future__ import annotations

from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .contract import Reject

_UPDATABLE = {
    "status",
    "request_url",
    "request_params",
    "source_index_name",
    "source_index_created_at",
    "pages",
    "rows_announced",
    "rows_extracted",
    "rows_rejected",
    "rows_loaded",
    "file_path",
    "file_sha256",
    "duplicate_of",
    "error",
    "finished_at",
}


def create_batch(
    conn: psycopg.Connection, *, batch_id: str, dataset: str, partition: str, mode: str
) -> None:
    conn.execute(
        "insert into ops.batch (batch_id, dataset, partition_value, mode, status)"
        " values (%s, %s, %s, %s, 'running')",
        (batch_id, dataset, partition, mode),
    )


def update_batch(conn: psycopg.Connection, batch_id: str, **fields: Any) -> None:
    unknown = set(fields) - _UPDATABLE
    if unknown:
        raise ValueError(f"cannot update ops.batch columns {sorted(unknown)}")
    values = [Jsonb(v) if isinstance(v, (dict, list)) else v for v in fields.values()]
    assignments = sql.SQL(", ").join(
        sql.SQL("{} = %s").format(sql.Identifier(name)) for name in fields
    )
    conn.execute(
        sql.SQL("update ops.batch set {} where batch_id = %s").format(assignments),
        (*values, batch_id),
    )


def latest_loaded(
    conn: psycopg.Connection, dataset: str, partition: str
) -> tuple[str, str] | None:
    """(batch_id, file_sha256) of the most recent loaded batch for this partition."""
    return conn.execute(
        "select batch_id, file_sha256 from ops.batch"
        " where dataset = %s and partition_value = %s and status = 'loaded'"
        " order by started_at desc, batch_id desc limit 1",
        (dataset, partition),
    ).fetchone()


def add_rejects(conn: psycopg.Connection, batch_id: str, rejects: list[Reject]) -> None:
    if not rejects:
        return
    with conn.cursor() as cur:
        cur.executemany(
            "insert into ops.batch_reject"
            " (batch_id, row_number, record_key, field, reason, raw_value)"
            " values (%s, %s, %s, %s, %s, %s) on conflict do nothing",
            [(batch_id, r.row_number, r.record_key, r.field, r.reason, r.raw_value)
             for r in rejects],
        )


def get_batch(conn: psycopg.Connection, batch_id: str) -> dict[str, Any]:
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute("select * from ops.batch where batch_id = %s", (batch_id,)).fetchone()
