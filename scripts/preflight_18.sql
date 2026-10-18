-- preflight_18.sql: SELECT-only. Run on live BEFORE pushing migration 18.
--   psql "$DATABASE_URL" -f scripts/preflight_18.sql
-- Every "abort if > 0" count must be 0 for migration 18 to apply. Nothing here writes.

select 'findings total'                                   as check, count(*) as n from public.findings
union all
select 'non-lawyer-added with null/blank citation (abort if > 0)',
       count(*) from public.findings
       where coalesce(advocate_action, '') <> 'add' and (citation is null or btrim(citation) = '')
union all
select 'citation the backfill cannot classify (abort if > 0)',
       count(*) from public.findings
       where citation is not null and btrim(citation) <> ''
         and citation !~ '^.+,\s*\d{4},\s*(s|ss)\.\s*\d'
         and citation !~ '^Internal:'
union all
select 'backfill -> STATUTORY',
       count(*) from public.findings where citation ~ '^.+,\s*\d{4},\s*(s|ss)\.\s*\d'
union all
select 'backfill -> INTERNAL_BASELINE',
       count(*) from public.findings
       where citation ~ '^Internal:' and citation !~ '^.+,\s*\d{4},\s*(s|ss)\.\s*\d';
