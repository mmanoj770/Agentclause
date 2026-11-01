-- Grants hardening. Re-applies the privilege intent of migrations 06, 07 and 09, which the
-- project move to the new Supabase project lost (a live drift check found anon/authenticated
-- holding full DML, TRUNCATE, TRIGGER and REFERENCES on every public table).
--
-- The version sorts before migrations 15 and 16 on purpose; the "17" in the name is only a tag.
-- Idempotent: every statement can be re-run. Touches only the public schema (not auth or storage).
-- RLS stays the access rule for reads: the policies are SELECT-only and `to authenticated`;
-- every write goes through FastAPI on a direct postgres connection.

-- (a) audit_logs is append-only: nobody may update, delete or truncate it (migration 06).
--     The no_update_delete / no_truncate triggers stay as the second line of defence.
revoke update, delete, truncate on table public.audit_logs from public, anon, authenticated, service_role;

-- (b) Tables: take everything back from anon and authenticated (migrations 07 and 09), then
--     give back SELECT only where an RLS policy serves that role.
--     service_role's privileges on tables other than audit_logs are left as they are.
revoke all on all tables in schema public from anon, authenticated;

-- Every SELECT policy in migrations 07 and 09 is `to authenticated`; none serves anon.
-- (profiles also has profiles_auth_admin_read for supabase_auth_admin, whose own SELECT
--  grant comes from migration 08 and is not touched here.)
grant select on table
  public.organizations,        -- organizations_read       (authenticated)
  public.profiles,             -- profiles_read            (authenticated)
  public.contract_types,       -- contract_types_read      (authenticated)
  public.documents,            -- documents_read           (authenticated)
  public.document_versions,    -- document_versions_read   (authenticated)
  public.findings,             -- findings_read            (authenticated)
  public.lawyer_assignments,   -- lawyer_assignments_read  (authenticated)
  public.audit_logs,           -- audit_logs_read          (authenticated)
  public.lawyer_conflicts      -- lawyer_conflicts_read    (authenticated)
to authenticated;

-- (c) Sequences: no direct use by the client roles.
revoke all on all sequences in schema public from anon, authenticated;

-- (d) RLS helper functions: migration 07 revoked these from public and anon.
--     authenticated keeps EXECUTE because the policies call them.
--     custom_access_token_hook is deliberately not touched (migrations 08 and 15 own its ACL).
revoke execute on function public.auth_user_role(), public.auth_org_id() from public, anon;
grant execute on function public.auth_user_role(), public.auth_org_id() to authenticated;

-- (e) Default privileges, so tables, sequences and functions created later in public
--     (the clauses tables, for example) do not start out with broad grants.
--     Written for the role that owns the migration-created objects (postgres).
--     Objects created by supabase_admin get supabase_admin's own default privileges, which this
--     migration cannot change; that role does not run migrations here.
--     Consequence: a new table that needs client reads must `grant select ... to authenticated`
--     explicitly, and a new function that policies call must `grant execute` explicitly.
alter default privileges for role postgres in schema public revoke all on tables    from anon, authenticated;
alter default privileges for role postgres in schema public revoke all on sequences from anon, authenticated;
alter default privileges for role postgres in schema public revoke all on functions from anon, authenticated;
