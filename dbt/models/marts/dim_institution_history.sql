-- SCD2 history of the institution attributes, read from the dbt snapshot.

select
    dbt_scd_id                as history_id,
    cert,
    institution_name,
    state_code,
    city,
    is_active,
    bank_class,
    primary_regulator,
    charter_code,
    end_date,
    dbt_valid_from            as valid_from,
    dbt_valid_to              as valid_to,
    dbt_valid_to is null      as is_current,
    batch_id                  as observed_in_batch_id
from {{ ref('snp_fdic__institutions') }}
