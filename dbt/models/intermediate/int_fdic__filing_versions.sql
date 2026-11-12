-- Every distinct content observed for a filing (DWH-04), with the reason it changed.
-- A batch reloads a whole quarter: a filing whose row is identical to the one in the previous
-- batch is not a new version and is left out.

with filings as (

    select
        batch_id,
        batch_mode,
        is_simulated,
        contract_version,
        batch_started_at,
        cert,
        report_date,
        row_hash,
        payload,
        lag(row_hash) over by_filing         as previous_row_hash,
        lag(payload) over by_filing          as previous_payload,
        lag(batch_id) over by_filing         as previous_batch_id,
        lag(is_simulated) over by_filing     as previous_is_simulated,
        lag(contract_version) over by_filing as previous_contract_version
    from {{ ref('stg_fdic__financials') }}
    window by_filing as (partition by cert, report_date order by batch_started_at, batch_id)

),

versions as (

    select
        *,
        -- values of the fields present on both sides: a field added by the contract is not a change
        (
            select count(*)
            from jsonb_each(payload) as now_
            where previous_payload ? now_.key
              and previous_payload -> now_.key is distinct from now_.value
        ) as changed_fields
    from filings
    where previous_row_hash is null or row_hash <> previous_row_hash

)

select
    cert || '|' || to_char(report_date, 'YYYYMMDD') || '|' || batch_id as filing_version_id,
    cert || '|' || to_char(report_date, 'YYYYMMDD')                    as filing_id,
    cert,
    report_date,
    row_number() over by_filing                                        as version_number,
    batch_id,
    batch_mode,
    is_simulated,
    contract_version,
    batch_started_at                                                    as valid_from,
    lead(batch_started_at) over by_filing                               as valid_to,
    lead(batch_id) over by_filing is null                               as is_latest,
    previous_batch_id,
    case
        when previous_batch_id is null then 'initial'
        when changed_fields = 0 and contract_version <> previous_contract_version
            then 'contract_change'
        when is_simulated then 'simulated'
        when previous_is_simulated then 'restored_after_simulation'
        else 'revision'
    end                                                                 as change_kind,
    changed_fields,
    row_hash,
    payload,
    previous_payload
from versions
window by_filing as (partition by cert, report_date order by batch_started_at, batch_id)
