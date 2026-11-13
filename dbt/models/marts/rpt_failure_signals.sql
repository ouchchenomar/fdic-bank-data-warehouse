-- DWH-08 back-test: for each bank that failed while the warehouse covers it, its filings
-- before the failure and the early-warning signals they carried.

select
    f.failure_id || '|' || to_char(p.report_date, 'YYYYMMDD')  as failure_signal_id,
    f.failure_id,
    f.cert,
    f.institution_name,
    f.state_code,
    f.failure_date,
    f.estimated_loss_kusd,
    p.report_date,
    p.report_quarter_label,
    row_number() over (partition by f.failure_id order by p.report_date desc)
                                                                as quarters_before_failure,
    p.total_assets_kusd,
    p.noncurrent_loans_ratio_pct,
    p.equity_to_assets_pct,
    p.tier1_leverage_ratio_pct,
    p.roa_pct,
    p.signal_capital,
    p.signal_asset_quality,
    p.signal_earnings,
    p.signal_count,
    p.batch_id
from {{ ref('fct_failures') }} as f
join {{ ref('fct_filings') }} as p
    on p.cert = f.cert and p.report_date < f.failure_date
