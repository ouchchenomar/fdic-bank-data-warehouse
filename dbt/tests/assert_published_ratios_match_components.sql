-- DWH-07: a ratio published by the FDIC must match the ratio recomputed from its
-- components, within 0.01 percentage point. A zero denominator is skipped: the FDIC
-- publishes 0 in that case (e.g. CERT 34065 has no deposits on 2026-06-30).
-- Checked on the current filings, the ones that get published.

with checks as (

    select filing_id, cert, report_date, batch_id, 'EQV' as ratio,
           equity_to_assets_pct as published,
           equity_capital_kusd / nullif(total_assets_kusd, 0) * 100 as recomputed
    from {{ ref('fct_filings') }}

    union all

    select filing_id, cert, report_date, batch_id, 'LNLSDEPR' as ratio,
           loans_to_deposits_pct as published,
           net_loans_kusd / nullif(total_deposits_kusd, 0) * 100 as recomputed
    from {{ ref('fct_filings') }}

)

select *, published - recomputed as gap
from checks
where published is not null
  and recomputed is not null
  and abs(published - recomputed) > 0.01
