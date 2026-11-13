"""Gated publication (DWH-05): publish the marts only when every dbt test passes.

Each publication copies the marts into a new schema pub_<timestamp>. The views of the
`published` schema, which the dashboard reads, are then switched to it in one transaction.
A refused build leaves those views untouched, and rollback() points them back to the
previous publication.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

_LOCK = 4_170_501  # advisory lock id: one publication at a time

PUBLISHED_TABLES = (
    "dim_institution",
    "dim_institution_history",
    "fct_filings",
    "fct_filing_versions",
    "fct_failures",
    "rpt_failure_signals",
    "rpt_watchlist",
    "rpt_filing_revisions",
    "rpt_reconciliation_qbp",
    "rpt_batches",
)


@dataclass
class BuildResult:
    success: bool
    counts: dict[str, int] = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PublicationOutcome:
    publication_id: str
    status: str
    target_schema: str | None
    previous_schema: str | None
    table_rows: dict[str, int] | None
    error: str | None


def current_schema(conn: psycopg.Connection) -> str | None:
    row = conn.execute(
        "select target_schema from ops.publication where status = 'published'"
        " order by finished_at desc, publication_id desc limit 1"
    ).fetchone()
    return row[0] if row else None


def _switch_views(conn: psycopg.Connection, schema: str, tables: tuple[str, ...]) -> None:
    conn.execute("create schema if not exists published")
    for table in tables:
        view = sql.Identifier("published", table)
        conn.execute(sql.SQL("drop view if exists {}").format(view))
        conn.execute(
            sql.SQL("create view {} as select * from {}").format(
                view, sql.Identifier(schema, table)
            )
        )


def _finish(conn: psycopg.Connection, publication_id: str, **values) -> PublicationOutcome:
    values = {k: Jsonb(v) if isinstance(v, dict) else v for k, v in values.items()}
    assignments = sql.SQL(", ").join(
        sql.SQL("{} = %s").format(sql.Identifier(k)) for k in [*values, "finished_at"]
    )
    conn.execute(
        sql.SQL("update ops.publication set {} where publication_id = %s").format(assignments),
        (*values.values(), datetime.now(UTC), publication_id),
    )
    conn.commit()
    row = conn.execute(
        "select status, target_schema, previous_schema, table_rows, error"
        " from ops.publication where publication_id = %s",
        (publication_id,),
    ).fetchone()
    return PublicationOutcome(publication_id, *row)


def publish(
    conn: psycopg.Connection,
    build: Callable[[], BuildResult],
    *,
    source_schema: str = "marts",
    tables: tuple[str, ...] = PUBLISHED_TABLES,
    keep: int = 3,
) -> PublicationOutcome:
    if not conn.execute("select pg_try_advisory_lock(%s)", (_LOCK,)).fetchone()[0]:
        raise RuntimeError("another publication is running")
    try:
        return _publish(conn, build, source_schema, tables, keep)
    finally:
        conn.rollback()
        conn.execute("select pg_advisory_unlock(%s)", (_LOCK,))
        conn.commit()


def _publish(conn, build, source_schema, tables, keep) -> PublicationOutcome:
    now = datetime.now(UTC)
    publication_id = f"pub_{now:%Y%m%dT%H%M%S}{now.microsecond // 1000:03d}z"
    previous = current_schema(conn)
    conn.execute(
        "insert into ops.publication (publication_id, status, previous_schema)"
        " values (%s, 'running', %s)",
        (publication_id, previous),
    )
    conn.commit()

    try:
        result = build()
    except Exception as exc:  # noqa: BLE001 - a crashed build is a refused publication
        result = BuildResult(False, failures=[f"{type(exc).__name__}: {exc}"])
    if not result.success:
        reason = "dbt build failed: " + "; ".join(result.failures[:10] or ["unknown error"])
        return _finish(conn, publication_id, status="refused", dbt_summary=result.counts,
                       error=reason)

    try:
        target = sql.Identifier(publication_id)
        conn.execute(sql.SQL("create schema {}").format(target))
        rows = {}
        for table in tables:
            conn.execute(
                sql.SQL("create table {} as select * from {}").format(
                    sql.Identifier(publication_id, table), sql.Identifier(source_schema, table)
                )
            )
            rows[table] = conn.execute(
                sql.SQL("select count(*) from {}").format(sql.Identifier(publication_id, table))
            ).fetchone()[0]
        _switch_views(conn, publication_id, tables)
        # Copy, view switch and log are committed together: readers see old or new, never half.
        outcome = _finish(conn, publication_id, status="published", target_schema=publication_id,
                          dbt_summary=result.counts, table_rows=rows)
    except Exception as exc:  # noqa: BLE001 - the attempt must be logged
        conn.rollback()
        return _finish(conn, publication_id, status="refused", dbt_summary=result.counts,
                       error=f"{type(exc).__name__}: {exc}"[:2000])

    _drop_old_publications(conn, keep)
    return outcome


def rollback(conn: psycopg.Connection, tables: tuple[str, ...] = PUBLISHED_TABLES) -> str:
    """Point the published views back to the previous publication still on disk."""
    rows = conn.execute(
        "select publication_id, target_schema from ops.publication where status = 'published'"
        " and exists (select 1 from information_schema.schemata where schema_name = target_schema)"
        " order by finished_at desc, publication_id desc limit 2"
    ).fetchall()
    if len(rows) < 2:
        raise LookupError("no earlier publication to roll back to")
    (current_id, _), (_, earlier_schema) = rows
    _switch_views(conn, earlier_schema, tables)
    conn.execute(
        "update ops.publication set status = 'rolled_back' where publication_id = %s",
        (current_id,),
    )
    conn.commit()
    return earlier_schema


def _drop_old_publications(conn: psycopg.Connection, keep: int) -> None:
    kept = [
        r[0]
        for r in conn.execute(
            "select target_schema from ops.publication where status = 'published'"
            " order by finished_at desc, publication_id desc limit %s",
            (keep,),
        )
    ]
    existing = [
        r[0]
        for r in conn.execute(
            "select schema_name from information_schema.schemata where schema_name like 'pub\\_%'"
        )
    ]
    for schema in existing:
        if schema not in kept:
            conn.execute(sql.SQL("drop schema {} cascade").format(sql.Identifier(schema)))
    conn.commit()


def publication_report(conn: psycopg.Connection, limit: int = 10) -> str:
    rows = conn.execute(
        "select publication_id, status, target_schema, previous_schema,"
        " coalesce(table_rows ->> 'fct_filings', ''), coalesce(left(error, 120), '')"
        " from ops.publication order by started_at desc limit %s",
        (limit,),
    ).fetchall()
    if not rows:
        return "no publication yet"
    head = ("publication", "status", "schema", "previous", "fct_filings", "error")
    lines = [head, *[tuple("" if v is None else str(v) for v in r) for r in rows]]
    widths = [max(len(line[i]) for line in lines) for i in range(len(head) - 1)]
    return "\n".join(
        "  ".join(v.ljust(w) for v, w in zip(line[:-1], widths, strict=True)) + "  " + line[-1]
        for line in lines
    )
