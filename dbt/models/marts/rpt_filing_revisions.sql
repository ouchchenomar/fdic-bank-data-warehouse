-- Field-level differences between two versions of a filing: what changed, from what, to what.
-- Contract changes are left out: they add fields without changing any value.

select
    v.filing_version_id || '|' || changed.key        as revision_id,
    v.filing_id,
    v.cert,
    v.report_date,
    v.version_number,
    v.change_kind,
    v.is_simulated,
    v.previous_batch_id,
    v.batch_id,
    v.valid_from                                      as changed_at,
    changed.key                                       as source_field,
    v.previous_payload ->> changed.key                as previous_value,
    changed.value #>> '{}'                            as new_value,
    case
        when jsonb_typeof(changed.value) = 'number'
         and jsonb_typeof(v.previous_payload -> changed.key) = 'number'
            then (changed.value #>> '{}')::numeric
               - (v.previous_payload ->> changed.key)::numeric
    end                                               as delta
from {{ ref('int_fdic__filing_versions') }} as v
cross join lateral jsonb_each(v.payload) as changed
where v.change_kind in ('revision', 'simulated', 'restored_after_simulation')
  and v.previous_payload ? changed.key
  and v.previous_payload -> changed.key is distinct from changed.value
