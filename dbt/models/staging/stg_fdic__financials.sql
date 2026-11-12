-- Typed quarterly filings, one row per loaded batch and (CERT, REPDTE).
-- Every version observed is kept: picking the current one happens downstream.

with loaded_batches as (
    select batch_id, mode, source_index_name, started_at
    from {{ source('ops', 'batch') }}
    where dataset = 'financials' and status = 'loaded'
)

select
    r.batch_id || '|' || r.record_key        as batch_record_id,
    r.batch_id,
    b.mode                                    as batch_mode,
    b.source_index_name,
    b.started_at                              as batch_started_at,
    r.record_key,
    r.row_hash,

    {{ json_int('CERT') }}                    as cert,
    {{ json_date('REPDTE', 'YYYYMMDD') }}     as report_date,

    -- amounts in thousands of US dollars
    {{ json_num('ASSET') }}                   as total_assets_kusd,
    {{ json_num('DEP') }}                     as total_deposits_kusd,
    {{ json_num('LNLSNET') }}                 as net_loans_kusd,
    {{ json_num('EQ') }}                      as equity_capital_kusd,
    {{ json_num('NCLNLS') }}                  as noncurrent_loans_kusd,
    {{ json_num('RBCT1J') }}                  as tier1_capital_kusd,
    -- year-to-date amounts: cumulated since January 1
    {{ json_num('NETINC') }}                  as net_income_ytd_kusd,
    {{ json_num('INTINC') }}                  as interest_income_ytd_kusd,

    -- ratios in percentage points, as published by the FDIC
    {{ json_num('ROA') }}                     as roa_pct,
    {{ json_num('ROE') }}                     as roe_pct,
    {{ json_num('NIMY') }}                    as net_interest_margin_pct,
    {{ json_num('EEFFR') }}                   as efficiency_ratio_pct,
    {{ json_num('EQV') }}                     as equity_to_assets_pct,
    {{ json_num('LNLSDEPR') }}                as loans_to_deposits_pct,
    {{ json_num('NCLNLSR') }}                 as noncurrent_loans_ratio_pct,
    {{ json_num('NTLNLSR') }}                 as net_chargeoffs_ratio_pct,
    {{ json_num('RBC1AAJ') }}                 as tier1_leverage_ratio_pct

from {{ source('raw', 'fdic_financials') }} as r
join loaded_batches as b on b.batch_id = r.batch_id
