"""Command line: python run.py <command>. Replaces a Makefile (make is not required)."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import date

from psycopg import sql

from .client import FdicClient
from .config import ROOT, load_settings
from .contract import load_contract
from .db import apply_migrations, connect
from .orchestration import plan_quarters
from .pipeline import Outcome, ingest
from .publish import PUBLISHED_TABLES, BuildResult, publication_report, publish, rollback
from .quarters import quarter_range, quarter_to_repdte, repdte_to_quarter
from .report import batch_report
from .sample import DEFAULT_CERTS, make_sample
from .simulate import SimulatedSource, parse_value
from .sources import ApiSource, OfflineSource

DATASETS = ("financials", "institutions", "failures")


def _print_outcome(outcome: Outcome) -> None:
    counts = (
        f"announced={outcome.rows_announced} extracted={outcome.rows_extracted} "
        f"rejected={outcome.rows_rejected} loaded={outcome.rows_loaded}"
    )
    print(f"[{outcome.status:9}] {outcome.batch_id}  {counts}")
    if outcome.duplicate_of:
        print(f"            same file as {outcome.duplicate_of}: nothing loaded")
    if outcome.error:
        print(f"            error: {outcome.error}")


def cmd_db_init(_args) -> int:
    settings = load_settings()
    with connect(settings.conninfo) as conn:
        for name in apply_migrations(conn, ROOT / "sql"):
            print(f"applied {name}")
        if settings.reader_password:
            conn.execute(sql.SQL("alter role fdic_reader login password {}").format(
                sql.Literal(settings.reader_password)))
            conn.commit()
            print("fdic_reader can log in (password: FDIC_READER_PASSWORD in .env)")
    return 0


def cmd_ingest(args) -> int:
    settings = load_settings()
    specs = load_contract(settings.contract_path)
    if args.offline:
        source = OfflineSource(settings.sample_dir)
    else:
        source = ApiSource(FdicClient(settings.api_base, page_size=args.page_size
                                      or settings.page_size))
    datasets = DATASETS if args.dataset == "all" else (args.dataset,)
    outcomes = []
    with connect(settings.conninfo) as conn:
        if args.offline and conn.execute(
            "select 1 from ops.batch where status = 'loaded' and mode = 'api' limit 1"
        ).fetchone():
            raise SystemExit(
                "offline mode is for an empty database: this one already holds API batches, "
                "and loading the sample would look like a new version of every quarter"
            )
        for name in datasets:
            spec = specs[name]
            if spec.partition_field:
                if args.last:
                    partitions = _last_loaded_partitions(conn, name, args.last)
                elif args.quarters:
                    partitions = quarter_range(args.quarters)
                else:
                    raise SystemExit(
                        f"{name} is extracted by quarter: add --quarters 2025Q1:2026Q2 or --last 4"
                    )
            else:
                partitions = [None]
            for partition in partitions:
                outcome = ingest(conn, spec, source, settings.raw_dir, partition)
                _print_outcome(outcome)
                outcomes.append(outcome)
    return _exit_code(outcomes)


EXIT_NOT_PUBLISHED = 99  # Airflow's BashOperator marks a task "skipped" on this exit code


def _not_published(outcome: Outcome) -> bool:
    return outcome.status == "failed" and outcome.rows_announced == 0


def _exit_code(outcomes: list[Outcome]) -> int:
    """1 if a batch failed, 99 if the only failures are quarters not published yet, else 0."""
    failed = [o for o in outcomes if o.status == "failed"]
    if any(not _not_published(o) for o in failed):
        return 1
    return EXIT_NOT_PUBLISHED if failed else 0


def cmd_plan(args) -> int:
    settings = load_settings()
    with connect(settings.conninfo) as conn:
        loaded = [
            r[0]
            for r in conn.execute(
                "select distinct partition_value from ops.batch"
                " where dataset = 'financials' and status = 'loaded'"
            )
        ]
    today = date.fromisoformat(args.today) if args.today else date.today()
    try:
        planned = plan_quarters(loaded, today, include_window=args.window,
                                requested=args.quarters)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps([repdte_to_quarter(q) for q in planned]))
    return 0


def _last_loaded_partitions(conn, dataset: str, count: int) -> list[str]:
    """The most recent quarters already loaded: the window where the FDIC revises filings."""
    rows = conn.execute(
        "select distinct partition_value from ops.batch where dataset = %s and status = 'loaded'"
        " order by partition_value desc limit %s",
        (dataset, count),
    ).fetchall()
    if not rows:
        raise SystemExit(f"no loaded {dataset} quarter yet: start with --quarters")
    return sorted(r[0] for r in rows)


def cmd_simulate_revision(args) -> int:
    settings = load_settings()
    spec = load_contract(settings.contract_path)["financials"]
    with connect(settings.conninfo) as conn:
        source = SimulatedSource(
            conn, args.cert, args.field,
            value=None if args.value is None else parse_value(args.value),
            change_pct=args.change_pct,
        )
        outcome = ingest(conn, spec, source, settings.raw_dir, quarter_to_repdte(args.quarter))
    _print_outcome(outcome)
    if outcome.status == "loaded":
        print("            simulated batch loaded: the next publication will be refused until"
              " the quarter is extracted again:"
              f" run.py ingest financials --quarters {args.quarter}")
    return 0 if outcome.status == "loaded" else 1


def _dbt_build() -> BuildResult:
    load_settings()  # exports .env values that profiles.yml reads with env_var()
    from dbt.cli.main import dbtRunner

    dbt_dir = str(ROOT / "dbt")
    result = dbtRunner().invoke(["build", "--project-dir", dbt_dir, "--profiles-dir", dbt_dir])
    counts: Counter[str] = Counter()
    failures = []
    for node in getattr(result.result, "results", None) or []:
        status = str(getattr(node.status, "value", node.status))
        counts[status] += 1
        if status in ("fail", "error"):
            failures.append(f"{node.node.name} ({status}: {node.message})")
    if result.exception:
        failures.append(f"{type(result.exception).__name__}: {result.exception}")
    return BuildResult(bool(result.success), dict(counts), failures)


def cmd_publish(args) -> int:
    settings = load_settings()
    with connect(settings.conninfo) as conn:
        if args.rollback:
            schema = rollback(conn)
            print(f"published views now read {schema}")
            return 0
        outcome = publish(conn, _dbt_build)
    print(f"[{outcome.status}] {outcome.publication_id}")
    if outcome.status == "published":
        print(f"            published views now read {outcome.target_schema}"
              f" (previous: {outcome.previous_schema or 'none'})")
        for table in PUBLISHED_TABLES:
            print(f"            {table:24} {(outcome.table_rows or {}).get(table, ''):>8}")
    else:
        print(f"            published views unchanged: {outcome.previous_schema or 'none'}")
        print(f"            {outcome.error}")
    return 0 if outcome.status == "published" else 1


def cmd_publications(args) -> int:
    settings = load_settings()
    with connect(settings.conninfo) as conn:
        print(publication_report(conn, limit=args.limit))
    return 0


def cmd_report(args) -> int:
    settings = load_settings()
    with connect(settings.conninfo) as conn:
        print(batch_report(conn, limit=args.limit, dataset=args.dataset))
    return 0


def cmd_make_sample(args) -> int:
    settings = load_settings()
    specs = load_contract(settings.contract_path)
    certs = [int(c) for c in args.certs.split(",")] if args.certs else DEFAULT_CERTS
    with connect(settings.conninfo) as conn:
        for line in make_sample(conn, specs, settings.sample_dir, certs):
            print(line)
    return 0


def cmd_check(args) -> int:
    from .check import run_checks

    return run_checks(end_to_end=not args.no_end_to_end, keep=args.keep)


def cmd_dbt(args) -> int:
    load_settings()  # exports .env values that profiles.yml reads with env_var()
    from dbt.cli.main import dbtRunner

    dbt_dir = str(ROOT / "dbt")
    result = dbtRunner().invoke([*args.dbt_args, "--project-dir", dbt_dir,
                                 "--profiles-dir", dbt_dir])
    return 0 if result.success else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="run.py", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("db-init", help="create the ops and raw schemas").set_defaults(func=cmd_db_init)

    p = sub.add_parser("ingest", help="extract, archive, validate and load a dataset")
    p.add_argument("dataset", choices=(*DATASETS, "all"))
    window = p.add_mutually_exclusive_group()
    window.add_argument("--quarters", help="quarter or range, e.g. 2025Q4 or 2025Q1:2026Q2")
    window.add_argument("--last", type=int, metavar="N",
                        help="extract again the N most recent quarters already loaded (revisions)")
    p.add_argument("--offline", action="store_true", help="read the versioned sample instead")
    p.add_argument("--page-size", type=int, help="override FDIC_PAGE_SIZE")
    p.set_defaults(func=cmd_ingest)

    p = sub.add_parser("plan", help="print, as JSON, the quarters a scheduled run should extract")
    p.add_argument("--window", action="store_true",
                   help="add the revision window (the four most recent quarters loaded)")
    p.add_argument("--quarters", help="rerun these quarters instead, e.g. 2026Q2")
    p.add_argument("--today", help="reference date, YYYY-MM-DD (default: today)")
    p.set_defaults(func=cmd_plan)

    p = sub.add_parser("report", help="show the batch register")
    p.add_argument("--limit", type=int, default=30)
    p.add_argument("--dataset", choices=DATASETS)
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("make-sample", help="rebuild data/sample from the latest API batches")
    p.add_argument("--certs", help="comma-separated CERT list (default: built-in list)")
    p.set_defaults(func=cmd_make_sample)

    p = sub.add_parser("simulate-revision",
                       help="load a copy of the last batch of a quarter with one value changed")
    p.add_argument("--quarter", required=True, help="e.g. 2026Q2")
    p.add_argument("--cert", required=True, type=int)
    p.add_argument("--field", required=True, help="contract field, e.g. EQ")
    change = p.add_mutually_exclusive_group(required=True)
    change.add_argument("--value", help="new value")
    change.add_argument("--change-pct", type=float, help="relative change, e.g. 10 or -5")
    p.set_defaults(func=cmd_simulate_revision)

    p = sub.add_parser("publish", help="dbt build, then publish the marts if every test passes")
    p.add_argument("--rollback", action="store_true",
                   help="point the published views back to the previous publication")
    p.set_defaults(func=cmd_publish)

    p = sub.add_parser("publications", help="show the publication log")
    p.add_argument("--limit", type=int, default=10)
    p.set_defaults(func=cmd_publications)

    p = sub.add_parser("check", help="lint, tests, then an offline end-to-end run (as in CI)")
    p.add_argument("--no-end-to-end", action="store_true",
                   help="lint and tests only, no scratch database")
    p.add_argument("--keep", action="store_true", help="keep the scratch database <db>_ci")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("dbt", help="run dbt with the project's settings, e.g. run.py dbt build")
    p.add_argument("dbt_args", nargs=argparse.REMAINDER)
    p.set_defaults(func=cmd_dbt)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)
