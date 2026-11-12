-- Every filing must be dated on a quarter end (March 31, June 30, September 30, December 31).

select batch_record_id, report_date
from {{ ref('stg_fdic__financials') }}
where to_char(report_date, 'MM-DD') not in ('03-31', '06-30', '09-30', '12-31')
