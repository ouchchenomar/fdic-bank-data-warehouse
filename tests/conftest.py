from __future__ import annotations

from datetime import datetime

import psycopg
import pytest
from psycopg import sql

from fdic_dwh.config import ROOT, load_settings
from fdic_dwh.contract import load_contract
from fdic_dwh.db import apply_migrations


@pytest.fixture(scope="session")
def specs():
    return load_contract(ROOT / "contracts" / "fdic.yml")


def fake_row(spec, number, **values):
    """A row with every contract field filled, numbers set to `number`."""
    row = {}
    for f in spec.fields.values():
        if f.type in ("integer", "numeric"):
            row[f.name] = number
        elif f.type == "date":
            row[f.name] = datetime(2026, 6, 30).strftime(f.date_format)
        else:
            row[f.name] = f"{f.name.lower()} {number}"
    row.update(values)
    return row


@pytest.fixture(scope="session")
def test_conninfo():
    """A dedicated <db>_test database in the local container; skipped when it is not running."""
    settings = load_settings()
    test_db = f"{settings.pg_db}_test"
    try:
        with psycopg.connect(settings.conninfo, autocommit=True, connect_timeout=3) as admin:
            exists = admin.execute(
                "select 1 from pg_database where datname = %s", (test_db,)
            ).fetchone()
            if not exists:
                admin.execute(sql.SQL("create database {}").format(sql.Identifier(test_db)))
    except psycopg.OperationalError as exc:
        pytest.skip(f"local PostgreSQL not reachable ({exc.__class__.__name__}); "
                    "run docker compose up -d")
    conninfo = psycopg.conninfo.make_conninfo(settings.conninfo, dbname=test_db)
    with psycopg.connect(conninfo) as conn:
        apply_migrations(conn, ROOT / "sql")
    return conninfo


@pytest.fixture
def pg(test_conninfo):
    with psycopg.connect(test_conninfo) as conn:
        conn.execute(
            "truncate raw.fdic_financials, raw.fdic_institutions, raw.fdic_failures,"
            " ops.batch_reject, ops.batch, ops.publication"
        )
        conn.commit()
        yield conn
