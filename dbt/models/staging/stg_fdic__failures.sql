-- Typed bank failures, one row per loaded batch and FDIC record ID.
-- 488 failures from 1934 to 1976 have no CERT and cannot be linked to filings.

with loaded_batches as (
    select batch_id, started_at
    from {{ source('ops', 'batch') }}
    where dataset = 'failures' and status = 'loaded'
)

select
    r.batch_id || '|' || r.record_key           as batch_record_id,
    r.batch_id,
    b.started_at                                 as batch_started_at,
    r.row_hash,

    {{ json_text('ID') }}                        as failure_id,
    {{ json_int('CERT') }}                       as cert,
    {{ json_text('NAME') }}                      as institution_name,
    {{ json_text('CITY') }}                      as city,
    {{ json_text('PSTALP') }}                    as state_code,
    {{ json_date('FAILDATE', 'MM/DD/YYYY') }}    as failure_date,
    {{ json_int('FAILYR') }}                     as failure_year,
    {{ json_text('RESTYPE') }}                   as resolution_type,
    {{ json_text('RESTYPE1') }}                  as resolution_transaction_type,
    {{ json_text('SAVR') }}                      as insurance_fund,
    {{ json_text('CHCLASS1') }}                  as charter_class,
    {{ json_text('BIDNAME') }}                   as acquirer_name,

    -- amounts in thousands of US dollars
    {{ json_num('QBFASSET') }}                   as total_assets_at_failure_kusd,
    {{ json_num('QBFDEP') }}                     as total_deposits_at_failure_kusd,
    {{ json_num('COST') }}                       as estimated_loss_kusd

from {{ source('raw', 'fdic_failures') }} as r
join loaded_batches as b on b.batch_id = r.batch_id
