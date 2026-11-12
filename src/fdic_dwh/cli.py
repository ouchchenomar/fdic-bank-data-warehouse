"""Command line: python run.py <command>. Replaces a Makefile (make is not required)."""

from __future__ import annotations

import argparse

from .client import FdicClient
from .config import ROOT, load_settings
from .contract import load_contract
from .db import apply_migrations, connect
from .pipeline import Outcome, ingest
from .quarters import quarter_range
from .report import batch_report
from .sample import DEFAULT_CERTS, make_sample
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
                if not args.quarters:
                    raise SystemExit(
                        f"{name} is extracted by quarter: add --quarters 2025Q1:2026Q2"
                    )
                partitions = quarter_range(args.quarters)
            else:
                partitions = [None]
            for partition in partitions:
                outcome = ingest(conn, spec, source, settings.raw_dir, partition)
                _print_outcome(outcome)
                outcomes.append(outcome)
    return 1 if any(o.status == "failed" for o in outcomes) else 0


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
    p.add_argument("--quarters", help="quarter or range, e.g. 2025Q4 or 2025Q1:2026Q2")
    p.add_argument("--offline", action="store_true", help="read the versioned sample instead")
    p.add_argument("--page-size", type=int, help="override FDIC_PAGE_SIZE")
    p.set_defaults(func=cmd_ingest)

    p = sub.add_parser("report", help="show the batch register")
    p.add_argument("--limit", type=int, default=30)
    p.add_argument("--dataset", choices=DATASETS)
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("make-sample", help="rebuild data/sample from the latest API batches")
    p.add_argument("--certs", help="comma-separated CERT list (default: built-in list)")
    p.set_defaults(func=cmd_make_sample)

    p = sub.add_parser("dbt", help="run dbt with the project's settings, e.g. run.py dbt build")
    p.add_argument("dbt_args", nargs=argparse.REMAINDER)
    p.set_defaults(func=cmd_dbt)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)
