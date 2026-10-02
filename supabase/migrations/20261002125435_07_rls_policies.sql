-- Helper functions. security definer avoids infinite loops when a policy reads profiles.
create function public.auth_user_role()
returns user_role
language sql stable security definer set search_path = ''
as $$ select role from public.profiles where id = auth.uid() $$;

create function public.auth_org_id()
returns uuid
language sql stable security definer set search_path = ''
as $$ select org_id from public.profiles where id = auth.uid() $$;

revoke execute on function public.auth_user_role(), public.auth_org_id() from public, anon;
grant execute on function public.auth_user_role(), public.auth_org_id() to authenticated;

-- Turn RLS on for every table
alter table organizations       enable row level security;
alter table profiles            enable row level security;
alter table contract_types      enable row level security;
alter table documents           enable row level security;
alter table document_versions   enable row level security;
alter table findings            enable row level security;
alter table lawyer_assignments  enable row level security;
alter table audit_logs          enable row level security;

-- Logged-in clients can only read. All writes go through FastAPI.
revoke insert, update, delete on
  organizations, profiles, contract_types, documents, document_versions,
  findings, lawyer_assignments, audit_logs
from anon, authenticated;

-- contract_types: any logged-in user can read the list
create policy contract_types_read on contract_types
  for select to authenticated using (true);

-- profiles: your own, people in your org, and the lawyer assigned to your org's documents
create policy profiles_read on profiles
  for select to authenticated
  using (
    id = auth.uid()
    or (org_id is not null and org_id = public.auth_org_id())
    or id in (select assigned_lawyer_id from documents
              where org_id = public.auth_org_id() and assigned_lawyer_id is not null)
  );

-- documents: your org's documents; lawyers see the unclaimed queue plus what they claimed
create policy documents_read on documents
  for select to authenticated
  using (
    org_id = public.auth_org_id()
    or (
      public.auth_user_role() = 'lawyer'
      and (
        assigned_lawyer_id = auth.uid()
        or (state = 'pending_lawyer_review' and assigned_lawyer_id is null)
      )
    )
  );

-- organizations: your own org, or the org of a document you can see
create policy organizations_read on organizations
  for select to authenticated
  using (
    id = public.auth_org_id()
    or exists (select 1 from documents d where d.org_id = organizations.id)
  );

-- document_versions: if you can see the document, you can see its versions
create policy document_versions_read on document_versions
  for select to authenticated
  using (exists (select 1 from documents d where d.id = document_versions.document_id));

-- findings: lawyers only, for documents they can see
create policy findings_read on findings
  for select to authenticated
  using (
    public.auth_user_role() = 'lawyer'
    and exists (select 1 from documents d where d.id = findings.document_id)
  );

-- lawyer_assignments: the lawyer themselves, or the document's org
create policy lawyer_assignments_read on lawyer_assignments
  for select to authenticated
  using (
    lawyer_id = auth.uid()
    or exists (select 1 from documents d
               where d.id = lawyer_assignments.document_id
                 and d.org_id = public.auth_org_id())
  );

-- audit_logs: the org that owns the document, or the lawyer who claimed it
create policy audit_logs_read on audit_logs
  for select to authenticated
  using (
    document_id is not null
    and exists (select 1 from documents d
                where d.id = audit_logs.document_id
                  and (d.org_id = public.auth_org_id() or d.assigned_lawyer_id = auth.uid()))
  );
