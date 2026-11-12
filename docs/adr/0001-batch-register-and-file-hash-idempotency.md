# ADR 0001 · Batch register, canonical raw files and file-hash idempotency

**Status:** accepted, 2026-11-12

## Context

The FDIC republishes quarters when banks amend their Call Reports, the API can fail in the middle of a pagination, and the same quarter is re-extracted many times. Every figure must be traceable to the file and the run that produced it (DWH-01, DWH-03). Replaying the same file must not create rows or versions (REC-03).

## Decision

1. **Every attempt is a batch** in `ops.batch`, created before the first HTTP call. Failed, duplicate and loaded attempts all stay in the register with their counts, source index version (`meta.index`) and error.
2. **Raw files are canonical.** Rows are sorted on the contract key, keys are sorted, separators and line endings are fixed. The same content always produces the same bytes, whatever the page order or the operating system, so the SHA-256 of the file identifies the content.
3. **A batch whose hash equals the last loaded batch of the same partition is a duplicate.** It is registered, nothing is loaded.
4. **Validation happens before loading** (contract fields, keys, types, announced total). A refused batch keeps its file on disk for diagnosis but never reaches the raw tables.
5. **Rows and the `loaded` status are committed in one transaction.** A batch is never half loaded.
6. Raw tables keep the payload as `jsonb`. Typing happens in dbt staging, so a new FDIC field does not break the load.

## Consequences

- A revised quarter is loaded as a new batch. Both versions stay side by side, and dbt compares a hash per row to tell what changed (DWH-04).
- Comparing with the *last* loaded batch, not any loaded batch, means a value that changes and then changes back is still recorded as a new version.
- The offline sample must be loaded into an empty database only, otherwise it would look like a new version of every quarter. The CLI refuses that case.
