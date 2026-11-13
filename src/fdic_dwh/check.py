"""run.py check: the checks a pull request must pass, the same locally and in CI.

1. ruff lint;
2. pytest (the PostgreSQL tests run in <db>_test);
3. end-to-end without internet: a scratch database <db>_ci, the versioned sample loaded in
   offline mode, then dbt build and publication. Raw files go to a temporary folder, so the
   real archive in data/raw is never touched.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import psycopg
from psycopg import sql

from .config import ROOT, load_settings

SAMPLE_QUARTERS = "2025Q1:2026Q2"


def _step(title: str, command: list[str], env: dict[str, str] | None = None) -> None:
    print(f"\n=== {title}: {' '.join(command)}", flush=True)
    started = time.monotonic()
    result = subprocess.run(command, cwd=ROOT, env=env)
    elapsed = time.monotonic() - started
    if result.returncode != 0:
        raise SystemExit(f"check failed at '{title}' (exit {result.returncode}, {elapsed:.0f}s)")
    print(f"=== {title}: ok ({elapsed:.0f}s)", flush=True)


def _recreate(conninfo: str, database: str) -> None:
    with psycopg.connect(conninfo, autocommit=True) as admin:
        admin.execute(sql.SQL("drop database if exists {} with (force)").format(
            sql.Identifier(database)))
        admin.execute(sql.SQL("create database {}").format(sql.Identifier(database)))


def _drop(conninfo: str, database: str) -> None:
    with psycopg.connect(conninfo, autocommit=True) as admin:
        admin.execute(sql.SQL("drop database if exists {} with (force)").format(
            sql.Identifier(database)))


def run_checks(*, end_to_end: bool = True, keep: bool = False) -> int:
    python = sys.executable
    _step("lint", [python, "-m", "ruff", "check", "."])
    _step("tests", [python, "-m", "pytest", "-q"])
    if not end_to_end:
        return 0

    settings = load_settings()
    ci_db = f"{settings.pg_db}_ci"
    _recreate(settings.conninfo, ci_db)
    with tempfile.TemporaryDirectory(prefix="fdic_ci_") as tmp:
        shutil.copytree(settings.sample_dir, Path(tmp) / "sample")
        env = {**os.environ, "POSTGRES_DB": ci_db, "DATA_DIR": tmp}
        run = [python, str(ROOT / "run.py")]
        _step("schema", [*run, "db-init"], env)
        _step("offline load", [*run, "ingest", "all", "--quarters", SAMPLE_QUARTERS,
                               "--offline"], env)
        _step("build and publish", [*run, "publish"], env)
        ci_conninfo = psycopg.conninfo.make_conninfo(settings.conninfo, dbname=ci_db)
        with psycopg.connect(ci_conninfo) as conn:
            filings = conn.execute("select count(*) from published.fct_filings").fetchone()[0]
            status = conn.execute(
                "select status from ops.publication order by started_at desc limit 1"
            ).fetchone()[0]
        if not filings or status != "published":
            raise SystemExit(f"end-to-end check failed: {filings} filings, status {status}")
        print(f"\n=== end to end: {filings} filings published from the offline sample")
    if keep:
        print(f"    scratch database kept: {ci_db}")
    else:
        _drop(settings.conninfo, ci_db)
    print("\nall checks passed")
    return 0
