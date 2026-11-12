{#- Typed reads from the raw jsonb payload. An empty string is treated as missing (NULL). -#}

{% macro json_text(field) -%}
    nullif(payload ->> '{{ field }}', '')
{%- endmacro %}

{% macro json_int(field) -%}
    nullif(payload ->> '{{ field }}', '')::integer
{%- endmacro %}

{% macro json_num(field) -%}
    nullif(payload ->> '{{ field }}', '')::numeric
{%- endmacro %}

{% macro json_date(field, pg_format) -%}
    to_date(nullif(payload ->> '{{ field }}', ''), '{{ pg_format }}')
{%- endmacro %}
