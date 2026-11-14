-- REC-02, industry level: the published filings against the FDIC's Quarterly Banking Profile.
-- Same population as the QBP: insured institutions, so without the non-insured trust
-- companies (class NC) and the insured U.S. branches of foreign banks (class OI).
-- match            = equal within the published rounding (exact count, 0.05 bn of income)
-- within_tolerance = relative gap of 0.5% or less: the QBP is a snapshot taken about 55 days
--                    after the quarter, and filings are amended after it
-- gap              = anything larger, shown as is

{% set tolerance = 0.005 %}

with warehouse as (

    select
        report_date,
        count(*)::numeric                        as insured_institutions,
        sum(net_income_qtr_kusd) / 1000000.0     as net_income_bn
    from {{ ref('fct_filings') }}
    where is_insured_population
    group by report_date

),

reference as (

    select * from {{ ref('qbp_reference') }}

),

compared as (

    select
        coalesce(w.report_date, r.report_date)  as report_date,
        'insured_institutions'                  as measure,
        'count'                                 as unit,
        r.insured_institutions::numeric         as reference_value,
        w.insured_institutions                  as warehouse_value,
        0::numeric                              as rounding,
        r.source_url
    from warehouse as w
    full outer join reference as r on r.report_date = w.report_date

    union all

    select
        coalesce(w.report_date, r.report_date),
        'net_income_qtr',
        'usd_billions',
        r.net_income_bn,
        round(w.net_income_bn, 3),
        0.05,
        r.source_url
    from warehouse as w
    full outer join reference as r on r.report_date = w.report_date

)

select
    measure || '|' || to_char(report_date, 'YYYYMMDD')                   as reconciliation_id,
    report_date,
    extract(year from report_date) || '-Q' || extract(quarter from report_date)
                                                                          as report_quarter_label,
    measure,
    unit,
    reference_value,
    warehouse_value,
    warehouse_value - reference_value                                     as gap,
    round((warehouse_value - reference_value) / nullif(reference_value, 0), 5)
                                                                          as relative_gap,
    {{ tolerance }}                                                       as tolerance,
    case
        when reference_value is null then 'no_reference'
        when warehouse_value is null then 'not_loaded'
        when abs(warehouse_value - reference_value) <= rounding then 'match'
        when abs(warehouse_value - reference_value) <= abs(reference_value) * {{ tolerance }}
            then 'within_tolerance'
        else 'gap'
    end                                                                   as status,
    source_url
from compared
