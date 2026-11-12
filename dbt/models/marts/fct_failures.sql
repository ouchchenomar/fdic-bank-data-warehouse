-- Bank failures since 1934, with the last filing the warehouse holds before each failure:
-- the starting point of an early-warning view (assets and capital just before the failure).

with failures as (

    select *
    from {{ ref('stg_fdic__failures') }}
    where batch_id in ({{ current_batches('failures') }})

),

last_filing as (

    select distinct on (f.failure_id)
        f.failure_id,
        p.report_date             as last_report_date,
        p.total_assets_kusd       as last_total_assets_kusd,
        p.equity_to_assets_pct    as last_equity_to_assets_pct,
        p.tier1_leverage_ratio_pct as last_tier1_leverage_ratio_pct,
        p.roa_pct                 as last_roa_pct
    from failures as f
    join {{ ref('fct_filings') }} as p
        on p.cert = f.cert and p.report_date < f.failure_date
    order by f.failure_id, p.report_date desc

)

select
    f.failure_id,
    f.cert,
    f.institution_name,
    f.city,
    f.state_code,
    f.failure_date,
    f.failure_year,
    f.resolution_type,
    f.resolution_transaction_type,
    f.insurance_fund,
    f.charter_class,
    f.acquirer_name,
    f.total_assets_at_failure_kusd,
    f.total_deposits_at_failure_kusd,
    f.estimated_loss_kusd,
    l.last_report_date,
    l.last_total_assets_kusd,
    l.last_equity_to_assets_pct,
    l.last_tier1_leverage_ratio_pct,
    l.last_roa_pct,
    f.batch_id
from failures as f
left join last_filing as l on l.failure_id = f.failure_id
