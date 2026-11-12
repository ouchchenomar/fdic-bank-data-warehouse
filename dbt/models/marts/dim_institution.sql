-- One row per institution known to the warehouse: every CERT of the institutions endpoint,
-- plus the filers it does not list (class NC, mostly non-insured trust companies), whose
-- attributes come from their latest filing.

with institutions as (

    select * from {{ ref('int_fdic__institutions_latest') }}

),

filers as (

    select
        cert,
        institution_name,
        state_code,
        city,
        bank_class,
        report_date,
        row_number() over (partition by cert order by report_date desc) as recency,
        min(report_date) over (partition by cert)                       as first_report_date,
        max(report_date) over (partition by cert)                       as last_report_date,
        count(*) over (partition by cert)                               as filings_in_warehouse
    from {{ ref('fct_filings') }}

),

latest_filing as (

    select * from filers where recency = 1

),

failures as (

    select cert, max(failure_date) as last_failure_date, count(*) as failure_count
    from {{ ref('fct_failures') }}
    where cert is not null
    group by cert

)

select
    coalesce(i.cert, f.cert)                                   as cert,
    coalesce(i.institution_name, f.institution_name)           as institution_name,
    coalesce(i.state_code, f.state_code)                       as state_code,
    i.state_name,
    coalesce(i.city, f.city)                                   as city,
    coalesce(i.bank_class, f.bank_class)                       as bank_class,
    i.primary_regulator,
    i.charter_code,
    i.fed_rssd,
    i.is_active,
    i.established_date,
    i.end_date,
    i.insured_date,
    case when i.cert is not null then 'institutions' else 'filings' end as attribute_source,
    f.first_report_date,
    f.last_report_date,
    coalesce(f.filings_in_warehouse, 0)                        as filings_in_warehouse,
    x.last_failure_date,
    coalesce(x.failure_count, 0)                               as failure_count
from institutions as i
full outer join latest_filing as f on f.cert = i.cert
left join failures as x on x.cert = coalesce(i.cert, f.cert)
