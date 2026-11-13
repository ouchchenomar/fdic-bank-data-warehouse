"""FDIC warehouse: daily extraction, weekly revision window, gated publication.

Every day at 07:00 UTC:
1. apply the database migrations;
2. extract institutions and failures, and every quarter that has ended since the latest one
   loaded. A quarter the FDIC has not published yet ends as **skipped**, not failed;
3. on Mondays, also extract the four most recent quarters again to catch revisions (DWH-04);
4. run `dbt build` and publish only if every test passes (DWH-05). A failed extraction
   blocks the publication, and the dashboard keeps the last published state.

**Rerun a quarter**: clear its `ingest_quarter` task (one task per quarter, named after it),
or trigger the DAG with the `quarters` parameter, e.g. `2026Q2` or `2025Q1:2026Q2`.

Each task runs `run.py` in the project's virtual environment: the same commands as by hand.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta

from airflow.sdk import Param, dag, get_current_context, task

PYTHON = "/opt/fdic-venv/bin/python"
RUN_PY = "/opt/fdic/run.py"
RUN = f"{PYTHON} {RUN_PY}"


@dag(
    dag_id="fdic_warehouse",
    schedule="0 7 * * *",
    start_date=datetime(2026, 11, 1),
    catchup=False,
    max_active_runs=1,
    default_args={"retries": 1, "retry_delay": timedelta(minutes=15)},
    params={
        "quarters": Param(
            None,
            type=["null", "string"],
            description="Rerun these quarters only, e.g. 2026Q2 or 2025Q1:2026Q2.",
        ),
        "revision_window": Param(
            False,
            type="boolean",
            description="Also extract the four most recent quarters again (always on Mondays).",
        ),
    },
    tags=["fdic", "warehouse"],
    doc_md=__doc__,
)
def fdic_warehouse() -> None:
    @task.bash(retries=0)
    def migrate() -> str:
        return f"{RUN} db-init"

    @task.bash
    def ingest_institutions() -> str:
        return f"{RUN} ingest institutions"

    @task.bash
    def ingest_failures() -> str:
        return f"{RUN} ingest failures"

    @task
    def plan_quarters(params=None, dag_run=None) -> list[str]:
        run_date = dag_run.logical_date or dag_run.run_after
        command = [PYTHON, RUN_PY, "plan"]
        if params["quarters"]:
            command += ["--quarters", params["quarters"]]
        elif params["revision_window"] or run_date.weekday() == 0:
            command.append("--window")
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"run.py plan failed: {result.stderr or result.stdout}")
        quarters = json.loads(result.stdout.strip().splitlines()[-1])
        print(f"quarters to extract: {quarters or 'none'}")
        return quarters

    @task.bash(map_index_template="{{ quarter_label }}", max_active_tis_per_dag=2)
    def ingest_quarter(quarter: str) -> str:
        get_current_context()["quarter_label"] = quarter
        return f"{RUN} ingest financials --quarters {quarter}"

    @task.bash(retries=0, trigger_rule="none_failed")
    def publish() -> str:
        return f"{RUN} publish"

    @task.bash(retries=0, trigger_rule="all_done")
    def report() -> str:
        return f"{RUN} report --limit 20 && {RUN} publications --limit 5"

    @task.bash(retries=0, trigger_rule="all_done")
    def check_freshness() -> str:
        # Fails when no extraction has reached the source for 8 days: the pipeline is down.
        return f"{RUN} dbt source freshness"

    migrated = migrate()
    quarters = plan_quarters()
    extractions = [
        ingest_institutions(),
        ingest_failures(),
        ingest_quarter.expand(quarter=quarters),
    ]
    migrated >> [extractions[0], extractions[1], quarters]
    published = publish()
    extractions >> published >> [report(), check_freshness()]


fdic_warehouse()
