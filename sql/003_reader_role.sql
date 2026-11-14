-- Read-only role for the dashboard. It reads the published views and nothing else,
-- so Power BI never sees a mart while dbt is building it. Idempotent.
-- run.py db-init enables its login when FDIC_READER_PASSWORD is set in .env.

do $$
begin
    if not exists (select 1 from pg_roles where rolname = 'fdic_reader') then
        create role fdic_reader nologin;
    end if;
end $$;

create schema if not exists published;
grant usage on schema published to fdic_reader;
grant select on all tables in schema published to fdic_reader;
-- The views are recreated at every publication: grant them as they are created.
alter default privileges in schema published grant select on tables to fdic_reader;
