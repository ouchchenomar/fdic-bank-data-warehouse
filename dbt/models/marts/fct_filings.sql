-- Current version of each quarterly filing, with quarterly flows and lineage (DWH-03, DWH-04).
-- NETINC and INTINC are cumulated since January 1: the quarterly flow is this quarter minus
-- the previous one of the same year, and equals the year-to-date amount in Q1.

{% set insured = "coalesce(f.bank_class, '') not in ('NC', 'OI')" %}
{% set capital = "f.tier1_leverage_ratio_pct < " ~ var('ew_tier1_leverage_min_pct') %}
{% set asset_quality = "f.noncurrent_loans_ratio_pct > " ~ var('ew_noncurrent_loans_max_pct') %}
{% set earnings = "f.roa_pct < " ~ var('ew_roa_min_pct') %}

with current_filings as (

    select *
    from {{ ref('stg_fdic__financials') }}
    where batch_id in ({{ current_batches('financials') }})

),

versions as (

    select
        filing_id,
        count(*)                                                       as version_count,
        max(valid_from)                                                as last_changed_at,
        (array_agg(change_kind order by version_number desc))[1]      as last_change_kind,
        (array_agg(batch_id order by version_number desc))[1]         as last_changed_batch_id
    from {{ ref('int_fdic__filing_versions') }}
    group by filing_id

),

with_previous as (

    select
        f.*,
        extract(year from f.report_date)::int    as report_year,
        extract(quarter from f.report_date)::int as report_quarter,
        p.net_income_ytd_kusd                    as previous_net_income_ytd_kusd,
        p.interest_income_ytd_kusd               as previous_interest_income_ytd_kusd,
        p.cert is not null                       as has_previous_quarter
    from current_filings as f
    left join current_filings as p
        on p.cert = f.cert
        and p.report_date = (date_trunc('quarter', f.report_date) - interval '1 day')::date
        and extract(quarter from f.report_date) > 1

)

select
    f.cert || '|' || to_char(f.report_date, 'YYYYMMDD')  as filing_id,
    f.cert,
    f.report_date,
    f.report_year,
    f.report_quarter,
    f.report_year || '-Q' || f.report_quarter             as report_quarter_label,

    -- attributes as reported with the filing
    f.institution_name,
    f.state_code,
    f.city,
    f.bank_class,

    -- stocks at the report date, thousands of US dollars
    f.total_assets_kusd,
    f.total_deposits_kusd,
    f.net_loans_kusd,
    f.equity_capital_kusd,
    f.noncurrent_loans_kusd,
    f.tier1_capital_kusd,

    -- year-to-date amounts and the quarterly flows derived from them
    f.net_income_ytd_kusd,
    f.interest_income_ytd_kusd,
    case
        when f.report_quarter = 1 then f.net_income_ytd_kusd
        when f.has_previous_quarter then f.net_income_ytd_kusd - f.previous_net_income_ytd_kusd
    end                                                   as net_income_qtr_kusd,
    case
        when f.report_quarter = 1 then f.interest_income_ytd_kusd
        when f.has_previous_quarter
            then f.interest_income_ytd_kusd - f.previous_interest_income_ytd_kusd
    end                                                   as interest_income_qtr_kusd,
    case
        when f.report_quarter = 1 then 'q1_equals_ytd'
        when f.has_previous_quarter then 'ytd_difference'
        else 'previous_quarter_missing'
    end                                                   as flow_basis,

    -- ratios in percentage points, as published by the FDIC
    f.roa_pct,
    f.roe_pct,
    f.net_interest_margin_pct,
    f.efficiency_ratio_pct,
    f.equity_to_assets_pct,
    f.loans_to_deposits_pct,
    f.noncurrent_loans_ratio_pct,
    f.net_chargeoffs_ratio_pct,
    f.tier1_leverage_ratio_pct,

    -- QBP asset size groups (DWH-06 size filter)
    case
        when f.total_assets_kusd < 100000 then 'Under $100M'
        when f.total_assets_kusd < 1000000 then '$100M-$1B'
        when f.total_assets_kusd < 10000000 then '$1B-$10B'
        when f.total_assets_kusd < 250000000 then '$10B-$250B'
        else 'Over $250B'
    end                                                   as asset_size_group,
    case
        when f.total_assets_kusd < 100000 then 1
        when f.total_assets_kusd < 1000000 then 2
        when f.total_assets_kusd < 10000000 then 3
        when f.total_assets_kusd < 250000000 then 4
        else 5
    end                                                   as asset_size_order,

    -- Same population as the QBP: insured institutions. Non-insured trust companies (NC) and
    -- insured branches of foreign banks (OI) hold no capital of their own and report Tier 1,
    -- equity and ROA as 0, which would read as false capital signals.
    {{ insured }}                                         as is_insured_population,

    -- early-warning signals (DWH-08) for insured institutions, thresholds in dbt_project.yml
    {{ insured }} and coalesce({{ capital }}, false)      as signal_capital,
    {{ insured }} and coalesce({{ asset_quality }}, false) as signal_asset_quality,
    {{ insured }} and coalesce({{ earnings }}, false)     as signal_earnings,
    case when {{ insured }} then
        coalesce({{ capital }}, false)::int
        + coalesce({{ asset_quality }}, false)::int
        + coalesce({{ earnings }}, false)::int
    else 0 end                                            as signal_count,
    f.report_date = max(f.report_date) over ()            as is_latest_quarter,

    -- lineage: where the current values come from
    f.batch_id,
    f.batch_mode,
    f.is_simulated,
    f.contract_version,
    f.source_index_name,
    f.batch_started_at                                    as extracted_at,
    v.version_count,
    v.last_change_kind,
    v.last_changed_batch_id,
    v.last_changed_at
from with_previous as f
left join versions as v
    on v.filing_id = f.cert || '|' || to_char(f.report_date, 'YYYYMMDD')
