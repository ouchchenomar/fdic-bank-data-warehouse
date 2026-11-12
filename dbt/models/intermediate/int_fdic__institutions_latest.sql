-- Institutions as delivered by the latest loaded batch: the input of the SCD2 snapshot.

select
    cert,
    institution_name,
    state_code,
    state_name,
    city,
    is_active,
    bank_class,
    primary_regulator,
    charter_code,
    fed_rssd,
    established_date,
    -- 12/31/9999 is the FDIC's way of saying "still open"
    nullif(end_date, date '9999-12-31') as end_date,
    insured_date,
    last_report_date,
    batch_id,
    batch_started_at
from {{ ref('stg_fdic__institutions') }}
where batch_id in ({{ current_batches('institutions') }})
