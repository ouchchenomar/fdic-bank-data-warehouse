# ADR 0004 · Airflow orchestrates the same CLI commands, one task per quarter

**Status:** accepted, 2026-11-13

## Context

The warehouse must run without anyone at the keyboard:
- extract every new quarter as soon as the FDIC publishes it (REC-08);
- extract the recent quarters again to catch revisions (DWH-04);
- publish only what passed every test (DWH-05).

An operator must also be able to rerun a single quarter, and see why a run did nothing. The FDIC publishes a quarter about two months after it ends, on a date it does not announce in the API. Until then the API returns 0 rows for that quarter, which is normal and must not page anyone.

## Options considered

1. **Cron and a shell script.** Nothing to install, but no run history, no per-quarter rerun and no view of what was skipped.
2. **dbt Cloud or a managed scheduler.** Covers dbt only, not the Python extraction and the batch register, and adds an account and a cost.
3. **Airflow, with tasks that hold the logic** (Python operators importing the pipeline). The orchestrator and the pipeline then share one Python environment, and the pipeline can only run through Airflow.
4. **Airflow, with tasks that call `run.py`.** The DAG only decides what to run and in which order. Every task is a command an operator can also type by hand.

## Decision

Option 4, on Airflow 3.3 (`airflow standalone` in Docker Compose, under the profile `airflow`).

1. **Separate environments.** The image installs the project's `requirements.txt` in its own virtual environment (`/opt/fdic-venv`), apart from Airflow's own packages. dbt and Airflow never share dependency pins.
2. **The plan is computed by the pipeline, not the DAG.** `run.py plan` reads the batch register and prints the quarters to extract as JSON: every quarter ended since the latest one loaded, and the four latest loaded quarters on Mondays or on request. The rule is a pure function (`orchestration.py`) with unit tests.
3. **One mapped task per quarter.** `ingest_quarter` is expanded over the plan and each task is named after its quarter (`2026Q3`). Rerunning a quarter means clearing that task, or triggering the DAG with the parameter `quarters`.
4. **"Not published yet" is a skip, not a failure.** A quarter the source announces with 0 rows ends with exit code 99, which the Bash task maps to *skipped*. Any other failure (contract violation, incomplete source, API down after the retries) exits 1 and fails the task.
5. **Publication is gated twice.** `publish` runs only if no extraction failed (`none_failed`), and `run.py publish` still refuses to publish if a dbt test fails (ADR 0003).
6. **Freshness alarm.** `dbt source freshness` on `ops.batch` warns after 2 days without a successful extraction and fails after 8: the pipeline is down even if every run looked green.
7. **Airflow keeps its metadata in a separate database (`airflow`) of the same PostgreSQL**, created on start-up.

## Consequences

- The DAG holds no business logic, so the same commands run by hand, in Airflow, and in CI (`run.py check`).
- A skipped `ingest_quarter` is the normal state for about two months after each quarter end. The batch register still records each attempt as `failed` with the reason "the source announces 0 rows".
- Every run publishes, even when every extraction was a duplicate. The new `pub_<timestamp>` schema then holds the same data, and only the last three are kept.
- `airflow standalone` is a single-machine setup for development and demonstration. A production deployment would run the scheduler, API server and workers as separate services, which the DAG does not need to change for.
