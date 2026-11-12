-- REC-04: a value made up by run.py simulate-revision may enter the history, never the
-- current figures. While a simulated batch is the current one, publication is refused.

select filing_id, batch_id, last_change_kind
from {{ ref('fct_filings') }}
where is_simulated
