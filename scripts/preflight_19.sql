-- preflight_19.sql: SELECT-only. Run BEFORE applying migration 19 (document_chunks).
-- Run:  psql "$DATABASE_URL" -f scripts/preflight_19.sql
-- Prints one PASS/FAIL row per precondition; FAIL rows sort first. Apply only if every row is PASS.

with checks as (
  select 'document_chunks does not exist yet' as expectation,
         to_regclass('public.document_chunks') is null as ok

  union all
  select 'documents exists', to_regclass('public.documents') is not null
  union all
  select 'document_versions exists', to_regclass('public.document_versions') is not null

  union all
  select 'pgvector extension is installed',
         exists (select 1 from pg_extension where extname = 'vector')
  union all
  select 'hnsw access method is available (pgvector >= 0.5)',
         exists (select 1 from pg_am where amname = 'hnsw')

  union all
  select 'clauses.embedding is vector(768)',
         exists (select 1 from pg_attribute a
                 where a.attrelid = to_regclass('public.clauses') and a.attname = 'embedding'
                   and format_type(a.atttypid, a.atttypmod) = 'vector(768)')

  union all
  select 'clauses has the migration 14 tracking columns',
         (select count(*) from information_schema.columns
          where table_schema = 'public' and table_name = 'clauses'
            and column_name in ('embedding_model', 'embedded_version', 'embedded_text_hash')) = 3

  union all
  select 'function document_chunks_check_document does not exist yet',
         to_regprocedure('public.document_chunks_check_document()') is null
)
select case when ok then 'PASS' else 'FAIL' end as result, expectation
from checks
order by ok, expectation;

-- For the record: server version and pgvector version.
select version() as server_version,
       (select extversion from pg_extension where extname = 'vector') as pgvector_version;
