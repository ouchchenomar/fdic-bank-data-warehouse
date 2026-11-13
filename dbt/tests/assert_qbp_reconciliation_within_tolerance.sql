-- REC-02: a gap above the tolerance with the Quarterly Banking Profile is reported as a
-- warning, not a refusal: the QBP is published once, the filings keep being amended.
{{ config(severity='warn') }}

select reconciliation_id, measure, reference_value, warehouse_value, relative_gap
from {{ ref('rpt_reconciliation_qbp') }}
where status = 'gap'
