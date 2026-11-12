"""PostgreSQL connection, schema setup and raw loading."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

from .contract import DatasetSpec
from .rawfiles import row_hash


def connect(conninfo: str) -> psycopg.Connection:
    return psycopg.connect(conninfo)


def apply_migrations(conn: psycopg.Connection, sql_dir: Path) -> list[str]:
    applied = []
    for path in sorted(sql_dir.glob("*.sql")):
        conn.execute(path.read_text(encoding="utf-8"))
        applied.append(path.name)
    conn.commit()
    return applied


def load_rows(
    conn: psycopg.Connection, spec: DatasetSpec, batch_id: str, rows: list[dict[str, Any]]
) -> int:
    """COPY rows into the dataset's raw table. The caller owns the transaction."""
    statement = sql.SQL("COPY {} (batch_id, record_key, row_hash, payload) FROM STDIN").format(
        sql.Identifier("raw", f"fdic_{spec.name}")
    )
    with conn.cursor() as cur, cur.copy(statement) as copy:
        copy.set_types(["text", "text", "text", "jsonb"])
        for row in rows:
            copy.write_row((batch_id, spec.record_key(row), row_hash(row), Jsonb(row)))
    return len(rows)
