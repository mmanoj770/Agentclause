-- verify_null_org.sql: a startup user with NO org must see nothing, through row-level security.
-- LOCAL DATABASE ONLY. Everything happens in one transaction that ends in ROLLBACK, so nothing persists.
-- Run (the local stack's supabase_admin can insert into auth.users; postgres cannot):
--   psql -h 127.0.0.1 -p 54322 -U supabase_admin -d postgres -f scripts/verify_null_org.sql
--
-- Fixtures (synthetic ids and .invalid emails): one organization with an owner, a document, a version,
-- a finding, a second unclaimed document waiting in the lawyer queue, a lawyer with an assignment and a
-- conflict, and an audit row. So "0 visible" means "filtered by RLS", not "table is empty".
-- Then, as role authenticated with JWT claims sub = the no-org user, no org_id claim, user_role =
-- startup_user, every table is counted. Expected: 0 everywhere except that user's own profile row (1).
-- A control run as the org owner shows the same tables are visible to someone who should see them.
-- RLS here keys off public.profiles via auth.uid(), not off the JWT's org_id claim.

begin;

-- ---- fixtures (as the admin role; the on_auth_user_created trigger creates each profile) ----
insert into auth.users (id, aud, role, email) values
  ('00000000-0000-0000-0000-00000000a001', 'authenticated', 'authenticated', 'owner@null-org-test.invalid'),
  ('00000000-0000-0000-0000-00000000a002', 'authenticated', 'authenticated', 'lawyer@null-org-test.invalid'),
  ('00000000-0000-0000-0000-00000000a003', 'authenticated', 'authenticated', 'noorg@null-org-test.invalid');

insert into organizations (id, name) values ('00000000-0000-0000-0000-00000000b001', 'Null-org test org');
update profiles set org_id = '00000000-0000-0000-0000-00000000b001' where id = '00000000-0000-0000-0000-00000000a001';
update profiles set role = 'lawyer', org_id = null where id = '00000000-0000-0000-0000-00000000a002';

insert into documents (id, org_id, created_by, doc_type, state, assigned_lawyer_id) values
  ('00000000-0000-0000-0000-00000000c001', '00000000-0000-0000-0000-00000000b001',
   '00000000-0000-0000-0000-00000000a001', 'nda', 'pending_lawyer_review', '00000000-0000-0000-0000-00000000a002');
insert into documents (id, org_id, created_by, doc_type, state) values
  ('00000000-0000-0000-0000-00000000c002', '00000000-0000-0000-0000-00000000b001',
   '00000000-0000-0000-0000-00000000a001', 'nda', 'pending_lawyer_review');
insert into document_versions (id, document_id, version_no, storage_key) values
  ('00000000-0000-0000-0000-00000000d001', '00000000-0000-0000-0000-00000000c001', 1, 'test/key');
insert into findings (document_id, document_version_id, layer, severity, description) values
  ('00000000-0000-0000-0000-00000000c001', '00000000-0000-0000-0000-00000000d001', 1, 'high', 'null-org test finding');
insert into lawyer_assignments (document_id, lawyer_id) values
  ('00000000-0000-0000-0000-00000000c001', '00000000-0000-0000-0000-00000000a002');
insert into lawyer_conflicts (lawyer_id, org_id) values
  ('00000000-0000-0000-0000-00000000a002', '00000000-0000-0000-0000-00000000b001');
insert into audit_logs (document_id, actor_id, actor_role, action) values
  ('00000000-0000-0000-0000-00000000c001', '00000000-0000-0000-0000-00000000a001', 'startup_user', 'null_org_test');

-- ---- what exists, as the admin role (all must be at least 1) ----
select 'seeded (admin view)' as view, tbl, n from (
  select 'documents' as tbl, count(*) as n from documents
  union all select 'document_versions', count(*) from document_versions
  union all select 'findings', count(*) from findings
  union all select 'lawyer_assignments', count(*) from lawyer_assignments
  union all select 'audit_logs', count(*) from audit_logs
  union all select 'lawyer_conflicts', count(*) from lawyer_conflicts
  union all select 'profiles', count(*) from profiles
  union all select 'organizations', count(*) from organizations
) s order by tbl;

-- the profile the trigger made for the no-org user: startup_user, org_id null
select 'no-org profile' as what, role::text, org_id from profiles where id = '00000000-0000-0000-0000-00000000a003';

-- ---- control: the org owner, who SHOULD see their own org's rows ----
set local role authenticated;
select set_config('request.jwt.claims',
  '{"sub":"00000000-0000-0000-0000-00000000a001","role":"authenticated","user_role":"startup_user","org_id":"00000000-0000-0000-0000-00000000b001"}', true);
select 'control: org owner' as who, tbl, visible from (
  select 'documents' as tbl, count(*) as visible from documents
  union all select 'document_versions', count(*) from document_versions
  union all select 'findings', count(*) from findings
  union all select 'lawyer_assignments', count(*) from lawyer_assignments
  union all select 'audit_logs', count(*) from audit_logs
  union all select 'lawyer_conflicts', count(*) from lawyer_conflicts
  union all select 'profiles', count(*) from profiles
  union all select 'organizations', count(*) from organizations
) s order by tbl;
reset role;

-- ---- the test: the user with no org ----
set local role authenticated;
select set_config('request.jwt.claims',
  '{"sub":"00000000-0000-0000-0000-00000000a003","role":"authenticated","user_role":"startup_user"}', true);
select case when visible = expected then 'PASS' else 'FAIL' end as result,
       'no-org user' as who, tbl, visible, expected
from (
  select 'documents' as tbl, count(*) as visible, 0 as expected from documents
  union all select 'document_versions', count(*), 0 from document_versions
  union all select 'findings', count(*), 0 from findings
  union all select 'lawyer_assignments', count(*), 0 from lawyer_assignments
  union all select 'audit_logs', count(*), 0 from audit_logs
  union all select 'lawyer_conflicts', count(*), 0 from lawyer_conflicts
  union all select 'profiles', count(*), 1 from profiles
  union all select 'organizations', count(*), 0 from organizations
) s order by tbl;

-- the one profile row they can see must be their own
select case when count(*) = 1 and bool_and(id = '00000000-0000-0000-0000-00000000a003') then 'PASS' else 'FAIL' end as result,
       'no-org user: the single visible profile is their own' as check
from profiles;
reset role;

rollback;
