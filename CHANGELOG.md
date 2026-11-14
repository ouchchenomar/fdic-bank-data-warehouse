# Changelog

All notable changes to this project are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/).

## [1.0.0] - 2026-11-14

First delivered version, run on the real FDIC data from Q1 2025 to Q2 2026.

### Ingestion

- Extraction of the FDIC BankFind endpoints `/financials`, `/institutions` and `/failures`: pages sorted on a stable key, retries with backoff on 429, 5xx and network errors, refusal of a batch when the source index changes during pagination.
- Canonical raw files with a manifest and a SHA-256 per batch, and the batch register `ops.batch`: replaying an identical file is recorded as `duplicate` and loads nothing.
- Data contract `contracts/fdic.yml` (version 2), checked before each load.
- Offline mode on a versioned sample of 14 banks.

### Warehouse

- dbt staging, filing versions labelled with the reason they exist, SCD2 history of the institutions, quarterly flows derived from year-to-date amounts.
- Marts with the lineage of every row: batch, FDIC index version and contract version.
- Gated publication: the `published` views switch to a new `pub_<timestamp>` schema only when every dbt test passes, and `publish --rollback` restores the previous one.
- Early-warning signals on insured institutions, back-test on the failures of 2025-2026 and watch list of the latest quarter.
- Reconciliation with the FDIC's Quarterly Banking Profile at industry level.

### Operations

- Airflow DAG `fdic_warehouse`: a daily run at 07:00 UTC, one task per quarter, a revision window on Mondays, quarters not yet published marked *skipped*.
- Docker Compose for PostgreSQL 16 and Airflow 3.3, both restarted with Docker.
- Read-only role `fdic_reader` for the dashboard.
- Runbook, acceptance report and four architecture decision records.

### Dashboard

- Power BI project generated from the published schema: a TMDL model and a four-page PBIR report.
- Drillthrough from any bank of the overview and early-warning pages to the institution page.

### Quality

- 64 Python tests and 65 dbt data tests.
- `python run.py check`: lint, tests and an offline end-to-end run in a scratch database, also available as an on-demand GitHub Actions workflow.
- pre-commit hooks.
- dbt documentation and lineage graph on GitHub Pages.

[1.0.0]: https://github.com/ouchchenomar/fdic-bank-data-warehouse/releases/tag/v1.0.0
