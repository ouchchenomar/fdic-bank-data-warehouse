-- Contract version per batch and publication log. Idempotent.

-- A change of contract (new field) must not be mistaken for a revision by the banks.
alter table ops.batch add column if not exists contract_version integer not null default 1;

-- One row per publication attempt (DWH-05): refused attempts are kept with their reason.
create table if not exists ops.publication (
    publication_id   text primary key,
    status           text not null check (status in ('running', 'published', 'refused', 'rolled_back')),
    target_schema    text,
    previous_schema  text,
    dbt_summary      jsonb,
    table_rows       jsonb,
    error            text,
    started_at       timestamptz not null default now(),
    finished_at      timestamptz
);
