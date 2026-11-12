-- Typed institution reference data, one row per loaded batch and CERT.
-- Dates use MM/DD/YYYY here, unlike REPDTE in the financials endpoint.

with loaded_batches as (
    select batch_id, started_at
    from {{ source('ops', 'batch') }}
    where dataset = 'institutions' and status = 'loaded'
)

select
    r.batch_id || '|' || r.record_key          as batch_record_id,
    r.batch_id,
    b.started_at                                as batch_started_at,
    r.row_hash,

    {{ json_int('CERT') }}                      as cert,
    {{ json_text('NAME') }}                     as institution_name,
    {{ json_text('STALP') }}                    as state_code,
    {{ json_text('STNAME') }}                   as state_name,
    {{ json_text('CITY') }}                     as city,
    {{ json_int('ACTIVE') }} = 1                as is_active,
    {{ json_text('BKCLASS') }}                  as bank_class,
    {{ json_text('REGAGNT') }}                  as primary_regulator,
    {{ json_text('CHARTER') }}                  as charter_code,
    {{ json_text('FED_RSSD') }}                 as fed_rssd,
    {{ json_date('ESTYMD', 'MM/DD/YYYY') }}     as established_date,
    -- 12/31/9999 means still open: kept as published, turned into NULL downstream if needed
    {{ json_date('ENDEFYMD', 'MM/DD/YYYY') }}   as end_date,
    {{ json_date('INSDATE', 'MM/DD/YYYY') }}    as insured_date,
    {{ json_date('REPDTE', 'MM/DD/YYYY') }}     as last_report_date

from {{ source('raw', 'fdic_institutions') }} as r
join loaded_batches as b on b.batch_id = r.batch_id
