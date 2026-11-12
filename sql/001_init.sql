-- Batch register and raw landing tables. Idempotent: safe to run again.

create schema if not exists ops;
create schema if not exists raw;

-- One row per extraction attempt, successful or not (DWH-01, REC-03).
create table if not exists ops.batch (
    batch_id                text primary key,
    dataset                 text not null,
    partition_value         text not null,
    mode                    text not null check (mode in ('api', 'offline', 'simulated')),
    status                  text not null check (status in ('running', 'extracted', 'failed', 'loaded', 'duplicate')),
    request_url             text,
    request_params          jsonb,
    source_index_name       text,
    source_index_created_at timestamptz,
    pages                   integer,
    rows_announced          integer,
    rows_extracted          integer,
    rows_rejected           integer,
    rows_loaded             integer,
    file_path               text,
    file_sha256             text,
    duplicate_of            text references ops.batch (batch_id),
    error                   text,
    started_at              timestamptz not null default now(),
    finished_at             timestamptz
);

create index if not exists batch_dataset_partition_idx
    on ops.batch (dataset, partition_value, status, started_at);

-- Rows refused by the data contract, with the reason (DWH-02).
create table if not exists ops.batch_reject (
    batch_id    text not null references ops.batch (batch_id),
    row_number  integer not null,
    record_key  text,
    field       text not null,
    reason      text not null,
    raw_value   text,
    primary key (batch_id, row_number, field)
);

-- Raw landing tables: the payload is kept as delivered, typing happens in dbt staging.
create table if not exists raw.fdic_financials (
    batch_id    text not null references ops.batch (batch_id),
    record_key  text not null,
    row_hash    text not null,
    payload     jsonb not null,
    primary key (batch_id, record_key)
);

create table if not exists raw.fdic_institutions (
    batch_id    text not null references ops.batch (batch_id),
    record_key  text not null,
    row_hash    text not null,
    payload     jsonb not null,
    primary key (batch_id, record_key)
);

create table if not exists raw.fdic_failures (
    batch_id    text not null references ops.batch (batch_id),
    record_key  text not null,
    row_hash    text not null,
    payload     jsonb not null,
    primary key (batch_id, record_key)
);
