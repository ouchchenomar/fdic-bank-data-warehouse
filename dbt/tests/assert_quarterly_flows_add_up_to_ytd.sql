-- The quarterly flows of a year, summed up to quarter n, must give the year-to-date amount
-- of quarter n. Checked wherever every quarter from Q1 to n is in the warehouse.

with running as (

    select
        filing_id,
        report_quarter,
        net_income_ytd_kusd,
        interest_income_ytd_kusd,
        count(*) over by_year                       as quarters_so_far,
        sum(net_income_qtr_kusd) over by_year       as net_income_running_kusd,
        sum(interest_income_qtr_kusd) over by_year  as interest_income_running_kusd
    from {{ ref('fct_filings') }}
    window by_year as (partition by cert, report_year order by report_date)

)

select *
from running
where quarters_so_far = report_quarter
  and (
      net_income_running_kusd is distinct from net_income_ytd_kusd
      or interest_income_running_kusd is distinct from interest_income_ytd_kusd
  )
