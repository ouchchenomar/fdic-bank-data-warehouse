-- Version history of every filing (DWH-04): one row per distinct content, oldest first.

select
    filing_version_id,
    filing_id,
    cert,
    report_date,
    version_number,
    batch_id,
    batch_mode,
    is_simulated,
    contract_version,
    change_kind,
    changed_fields,
    previous_batch_id,
    valid_from,
    valid_to,
    is_latest,
    row_hash
from {{ ref('int_fdic__filing_versions') }}
