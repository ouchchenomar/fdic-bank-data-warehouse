# ADR 0003 · Gated publication by switching views to a copied schema

**Status:** accepted, 2026-11-12

## Context

dbt rebuilds the marts in place. While a build runs, and after a build whose tests fail, the marts may hold data that no test has validated. The dashboard must keep showing the last validated state in both cases (DWH-05, REC-05, REC-06). It must also be possible to go back to the previous state without rerunning the pipeline.

## Options considered

1. **Dashboard reads the marts directly.** Simple, but a failed test does not stop bad data, and readers can see a half-built schema.
2. **Rename schemas (`marts` ↔ `published`).** Atomic, but dbt then builds into a schema the dashboard was reading, and keeping older states means more renames.
3. **Copy the marts into a new schema per publication, and switch views.** The dashboard reads views in `published`, which point to the latest `pub_<timestamp>` schema.

## Decision

Option 3.

1. `run.py publish` logs an attempt in `ops.publication`, then runs `dbt build`, which includes every data test.
2. If any model, snapshot or test fails, or dbt crashes, the attempt is marked `refused` with the failing nodes, and nothing else changes.
3. Otherwise the published tables are copied from `marts` to a new schema `pub_<timestamp>`. The views of `published` are dropped and recreated on it, and the attempt is marked `published`. All of this happens in one transaction, so readers see the old state or the new one, never a mix.
4. The last three published schemas are kept. `publish --rollback` points the views back to the previous one and marks the current one `rolled_back`.
5. A PostgreSQL advisory lock allows one publication at a time.

## Consequences

- The dashboard and any SQL user read `published.*` only: they never see the marts while dbt is building them.
- Each publication costs a full copy of the marts (about 140,000 rows today). That is acceptable at this size. A larger warehouse would publish by partition instead.
- A refused attempt is visible in `run.py publications` with its reason. That is the audit trail an AMOA team needs to explain why the dashboard did not change.
- The views are recreated on every publication, so a column added to a mart reaches `published` with no extra step.
