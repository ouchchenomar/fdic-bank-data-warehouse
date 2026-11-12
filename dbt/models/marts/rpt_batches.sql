-- Batch register as seen by the dashboard's operations page: every attempt, with its outcome.

select
    batch_id,
    dataset,
    partition_value,
    mode,
    status,
    contract_version,
    source_index_name,
    source_index_created_at,
    pages,
    rows_announced,
    rows_extracted,
    rows_rejected,
    rows_loaded,
    duplicate_of,
    error,
    file_sha256,
    started_at,
    finished_at,
    extract(epoch from finished_at - started_at)::numeric(10, 1) as duration_seconds,
    batch_id in (
        {{ current_batches('financials') }}
        union all {{ current_batches('institutions') }}
        union all {{ current_batches('failures') }}
    )                                                             as is_current
from {{ source('ops', 'batch') }}
