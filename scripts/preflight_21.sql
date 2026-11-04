-- preflight_21.sql: SELECT-only. Run BEFORE applying migration 21 (statutes).
-- Run:  psql "$DATABASE_URL" -f scripts/preflight_21.sql
-- Prints one PASS/FAIL row per precondition; FAIL rows sort first. Apply only if every row is PASS.

with checks as (
  select 'public.statutes does not exist yet' as expectation,
         to_regclass('public.statutes') is null as ok

  union all
  select 'btree_gist extension is available',
         exists (select 1 from pg_available_extensions where name = 'btree_gist')

  union all
  select 'verification_status enum has staging and verified labels',
         (select count(*) = 2
          from pg_enum e join pg_type t on t.oid = e.enumtypid
          where t.typname = 'verification_status' and e.enumlabel in ('staging', 'verified'))

  union all
  select 'set_updated_at function exists',
         to_regprocedure('public.set_updated_at()') is not null
)
select case when ok then 'PASS' else 'FAIL' end as result, expectation
from checks
order by ok, expectation;

-- Output available extension version and enum info for the record.
select name, default_version from pg_available_extensions where name = 'btree_gist';
select enumlabel from pg_enum e join pg_type t on t.oid = e.enumtypid
 where t.typname = 'verification_status' order by e.enumsortorder;
