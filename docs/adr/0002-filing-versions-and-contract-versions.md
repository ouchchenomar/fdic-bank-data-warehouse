# ADR 0002 · Filing versions, change kinds and contract versions

**Status:** accepted, 2026-11-12

## Context

The FDIC amends filings after their first publication, so the warehouse must keep each value it has shown together with the batch that brought it (DWH-04). Two other events also produce a new batch for a quarter, but are not revisions by the banks:
- **A change of our own contract.** Version 2 added four attributes to every filing, because 57 filers are missing from `/institutions`.
- **A simulated correction.** The test scenario needs a revision (REC-04) even when the FDIC has published none.

If every new batch were read as a revision, the revision report would show 26,559 "revisions" after the contract change, and a test value could reach the dashboard.

## Decision

1. **Each batch records the contract version it was validated against** (`ops.batch.contract_version`, also in the file manifest).
2. **A version is a distinct content of a filing**, so a filing whose row hash is unchanged in a new batch gets no new version. Since a batch reloads a whole quarter, a single revised bank produces a single version, not 4,000.
3. **Versions are compared on the fields present on both sides.** A field added by the contract is not a change.
4. **Each version carries a `change_kind`**, decided in this order:
   1. `initial`: the first content seen;
   2. `contract_change`: the contract version changed and no shared field changed;
   3. `simulated`: the batch was made by `run.py simulate-revision`;
   4. `restored_after_simulation`: the version that replaces a simulated one;
   5. `revision`: any other change, a real amendment by the FDIC.
5. **The current version of a filing comes from the latest loaded batch of its quarter**, simulated or not. The marts therefore show what the warehouse would publish, and the publication gate (ADR 0003) decides whether it may be published.
6. **Simulated batches go through the normal pipeline** (validation, hash, register) with `mode = 'simulated'`, and keep the base batch, the field, and the previous and new values in `request_params`.

## Consequences

- `rpt_filing_revisions` lists only changes of values, with source field, previous value, new value and delta.
- A real revision after a simulation is labelled `restored_after_simulation`. The field-level diff still shows exactly what changed, and the batch hash shows whether the content matches the last real extraction.
- The institutions history uses a dbt snapshot (`check` strategy) instead, because the endpoint has no report date. Its `valid_from` is the time the warehouse saw the change, not the date it took effect at the FDIC.
