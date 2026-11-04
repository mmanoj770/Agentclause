-- preflight_22.sql: SELECT-only. Run BEFORE applying migration 22 (statutes verified guard trigger).
-- Run:  psql "$DATABASE_URL" -f scripts/preflight_22.sql
-- Prints one PASS/FAIL row per precondition; FAIL rows sort first. Apply only if every row is PASS.

with checks as (
  select 'public.statutes table exists' as expectation,
         to_regclass('public.statutes') is not null as ok

  union all
  select 'public.statutes has status and evidence columns',
         (select count(*) = 4
          from information_schema.columns
          where table_schema = 'public'
            and table_name = 'statutes'
            and column_name in ('status', 'verified_by', 'verified_at', 'verification_ref'))

  union all
  select 'function statutes_guard_verified_edits does not exist yet',
         to_regprocedure('public.statutes_guard_verified_edits()') is null

  union all
  select 'trigger statutes_verified_guard does not exist yet',
         not exists (
           select 1 from pg_trigger
           where tgname = 'statutes_verified_guard'
             and tgrelid = 'public.statutes'::regclass
         )
)
select case when ok then 'PASS' else 'FAIL' end as result, expectation
from checks
order by ok, expectation;
