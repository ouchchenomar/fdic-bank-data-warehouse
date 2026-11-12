{#-
  The batch that holds the current state of each partition: the latest loaded one.
  A quarter extracted again with different content replaces the previous batch as a whole,
  so a filing withdrawn by the source also leaves the current state.
-#}

{% macro current_batches(dataset) -%}
    select batch_id
    from (
        select
            batch_id,
            row_number() over (
                partition by partition_value
                order by started_at desc, batch_id desc
            ) as recency
        from {{ source('ops', 'batch') }}
        where dataset = '{{ dataset }}' and status = 'loaded'
    ) as ranked
    where recency = 1
{%- endmacro %}
