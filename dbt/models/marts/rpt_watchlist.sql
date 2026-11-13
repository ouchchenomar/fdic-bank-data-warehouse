-- DWH-08 watch list: banks of the latest quarter with at least two early-warning signals,
-- with the signal count of the quarter before to show the trend.

with latest as (

    select * from {{ ref('fct_filings') }} where is_latest_quarter

),

previous as (

    select cert, signal_count
    from {{ ref('fct_filings') }}
    where report_date = (
        select (date_trunc('quarter', max(report_date)) - interval '1 day')::date
        from {{ ref('fct_filings') }}
    )

)

select
    l.filing_id,
    l.cert,
    l.institution_name,
    l.state_code,
    l.bank_class,
    l.asset_size_group,
    l.report_date,
    l.total_assets_kusd,
    l.noncurrent_loans_ratio_pct,
    l.equity_to_assets_pct,
    l.tier1_leverage_ratio_pct,
    l.roa_pct,
    l.signal_capital,
    l.signal_asset_quality,
    l.signal_earnings,
    l.signal_count,
    p.signal_count       as previous_signal_count,
    l.batch_id
from latest as l
left join previous as p on p.cert = l.cert
where l.signal_count >= 2
