-- verify_grants.sql: SELECT-only. Prints one PASS/FAIL row per expectation; FAIL rows sort first.
-- Run:  psql "$DATABASE_URL" -f scripts/verify_grants.sql
-- Expects migration 17 (grants hardening) to be applied. On a database without it, FAIL is the right answer.
--
-- Rules checked
--   anon           : no privilege of any kind on any public table or sequence
--   authenticated  : SELECT only, and only on tables with a SELECT policy for authenticated;
--                    nothing else on any public table, and no sequence privileges.
--                    `clauses` is deliberately closed to anon and authenticated (the frontend only
--                    uses Supabase for auth; clauses are read by the backend), so for it "no
--                    privileges" is the expected state even though it has a SELECT policy.
--   audit_logs     : nobody (public, anon, authenticated, service_role) has UPDATE, DELETE or TRUNCATE
--   functions      : anon cannot run auth_user_role()/auth_org_id(); authenticated can;
--                    custom_access_token_hook is closed to anon/authenticated and open to supabase_auth_admin
--   default privs  : postgres's defaults in public grant nothing to anon or authenticated
--   service_role   : still has SELECT and INSERT on audit_logs (it must keep writing the log)
--   columns        : anon and authenticated have no INSERT or UPDATE privilege on ANY column of any
--                    public table (has_column_privilege also counts table-level grants), in particular
--                    not on profiles.role or profiles.org_id
--   policies       : no non-SELECT RLS policy (INSERT/UPDATE/DELETE/ALL) applies to anon, authenticated
--                    or public on any public table, profiles above all

with t as (
  select c.oid, c.relname
  from pg_class c
  where c.relnamespace = 'public'::regnamespace and c.relkind in ('r', 'p')
), privs(p) as (
  values ('SELECT'), ('INSERT'), ('UPDATE'), ('DELETE'), ('TRUNCATE'), ('REFERENCES'), ('TRIGGER')
), checks as (

  -- anon: nothing on any table
  select format('anon has no %s on %s', p, relname) as expectation,
         not has_table_privilege('anon', t.oid, p) as ok
  from t cross join privs

  union all
  -- authenticated: SELECT exactly where a SELECT policy serves it
  select format('authenticated %s SELECT on %s',
                case when served then 'has' else 'has no' end, relname),
         has_table_privilege('authenticated', oid, 'SELECT') = served
  from (select t.oid, t.relname,
               exists (select 1 from pg_policies pp
                       where pp.schemaname = 'public' and pp.tablename = t.relname
                         and t.relname <> 'clauses'
                         and pp.cmd in ('SELECT', 'ALL')
                         and 'authenticated' = any (pp.roles)) as served
        from t) s

  union all
  -- authenticated: no write-side or other privilege on any table
  select format('authenticated has no %s on %s', p, relname),
         not has_table_privilege('authenticated', t.oid, p)
  from t cross join privs
  where p <> 'SELECT'

  union all
  -- audit_logs is append-only for every role that could have written to it
  select format('audit_logs append-only: %s has no %s', r, p),
         not has_table_privilege(r, 'public.audit_logs'::regclass, p)
  from (values ('public'), ('anon'), ('authenticated'), ('service_role')) as roles(r)
  cross join (values ('UPDATE'), ('DELETE'), ('TRUNCATE')) as ap(p)

  union all
  select 'service_role still has ' || p || ' on audit_logs',
         has_table_privilege('service_role', 'public.audit_logs'::regclass, p)
  from (values ('SELECT'), ('INSERT')) as sp(p)

  union all
  -- sequences
  select format('%s has no %s on sequence %s', r, p, c.relname),
         not has_sequence_privilege(r, c.oid, p)
  from pg_class c
  cross join (values ('anon'), ('authenticated')) as roles(r)
  cross join (values ('USAGE'), ('SELECT'), ('UPDATE')) as sp(p)
  where c.relnamespace = 'public'::regnamespace and c.relkind = 'S'

  union all
  -- RLS helper functions
  select 'anon cannot execute ' || f, not has_function_privilege('anon', ('public.' || f)::regprocedure, 'EXECUTE')
  from (values ('auth_user_role()'), ('auth_org_id()')) as fn(f)
  union all
  select 'authenticated can execute ' || f, has_function_privilege('authenticated', ('public.' || f)::regprocedure, 'EXECUTE')
  from (values ('auth_user_role()'), ('auth_org_id()')) as fn(f)

  union all
  -- access-token hook
  select r || ' cannot execute custom_access_token_hook',
         not has_function_privilege(r, 'public.custom_access_token_hook(jsonb)'::regprocedure, 'EXECUTE')
  from (values ('anon'), ('authenticated'), ('public')) as roles(r)
  union all
  select 'supabase_auth_admin can execute custom_access_token_hook',
         has_function_privilege('supabase_auth_admin', 'public.custom_access_token_hook(jsonb)'::regprocedure, 'EXECUTE')
  union all
  select 'supabase_auth_admin can SELECT profiles',
         has_table_privilege('supabase_auth_admin', 'public.profiles'::regclass, 'SELECT')

  union all
  -- default privileges of postgres in public: nothing for anon or authenticated
  select format('default privileges (postgres, public, %s) give nothing to %s', ot, r),
         not exists (
           select 1
           from pg_default_acl d, lateral aclexplode(d.defaclacl) a
           where pg_get_userbyid(d.defaclrole) = 'postgres'
             and d.defaclnamespace = 'public'::regnamespace
             and d.defaclobjtype = ot::"char"
             and a.grantee = (select oid from pg_roles where rolname = r))
  from (values ('r'), ('S'), ('f')) as o(ot)
  cross join (values ('anon'), ('authenticated')) as roles(r)

  union all
  -- profiles: nobody on the client side may write it (role and org_id decide who is a lawyer and
  -- which client a user belongs to, so a self-service write would be privilege escalation)
  select format('%s has no %s on profiles', r, p),
         not has_table_privilege(r, 'public.profiles'::regclass, p)
  from (values ('anon'), ('authenticated')) as roles(r)
  cross join (values ('INSERT'), ('UPDATE'), ('DELETE'), ('TRUNCATE')) as pp(p)

  union all
  -- column level, every public table: no INSERT or UPDATE privilege on any column
  select format('%s has no column-level %s on any column of %s', r, p, t.relname),
         not exists (
           select 1 from pg_attribute a
           where a.attrelid = t.oid and a.attnum > 0 and not a.attisdropped
             and has_column_privilege(r, t.oid, a.attnum, p))
  from t
  cross join (values ('anon'), ('authenticated')) as roles(r)
  cross join (values ('INSERT'), ('UPDATE')) as cp(p)

  union all
  -- the two profiles columns that matter most, named explicitly
  select format('%s cannot %s profiles.%s', r, p, col),
         not has_column_privilege(r, 'public.profiles'::regclass, col, p)
  from (values ('anon'), ('authenticated')) as roles(r)
  cross join (values ('INSERT'), ('UPDATE')) as cp(p)
  cross join (values ('role'), ('org_id')) as cc(col)

  union all
  -- column grants recorded in information_schema (a second view of the same facts)
  select format('information_schema.column_privileges: %s has no %s column grants in public', r, p),
         not exists (
           select 1 from information_schema.column_privileges cpv
           where cpv.table_schema = 'public' and cpv.grantee = r and cpv.privilege_type = p)
  from (values ('anon'), ('authenticated')) as roles(r)
  cross join (values ('INSERT'), ('UPDATE')) as cp(p)

  union all
  -- RLS: no write-side policy for the client roles, on any public table
  select format('no non-SELECT policy applies to anon/authenticated/public on %s', t.relname),
         not exists (
           select 1 from pg_policies pp
           where pp.schemaname = 'public' and pp.tablename = t.relname and pp.cmd <> 'SELECT'
             and pp.roles && array['anon', 'authenticated', 'public']::name[])
  from t
  union all
  select 'profiles has no non-SELECT policy for anon/authenticated/public (explicit)',
         not exists (
           select 1 from pg_policies pp
           where pp.schemaname = 'public' and pp.tablename = 'profiles' and pp.cmd <> 'SELECT'
             and pp.roles && array['anon', 'authenticated', 'public']::name[])
)
select case when ok then 'PASS' else 'FAIL' end as result, expectation
from checks
order by ok, expectation;
