-- Reusable helpers
create function set_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

create function reject_modification()
returns trigger language plpgsql as $$
begin
  raise exception '% on % is not allowed (append-only)', tg_op, tg_table_name;
end;
$$;

create table documents (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references organizations(id) on delete restrict,
  created_by uuid not null references profiles(id) on delete restrict,
  doc_type text not null references contract_types(code),
  state document_state not null default 'drafted',
  state_of_execution text,                 -- Indian state, drives stamp duty
  transaction_value numeric(18,2),
  triage_tier text check (triage_tier in ('standard', 'enhanced', 'senior_counsel')),
  assigned_lawyer_id uuid references profiles(id) on delete set null,  -- stays null until a lawyer claims it
  draft_for_settlement boolean not null default true,  -- delivery is blocked while true
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create trigger documents_set_updated_at
before update on documents
for each row execute function set_updated_at();

create index documents_org_id_idx on documents(org_id);
create index documents_state_idx on documents(state);
create index documents_assigned_lawyer_idx on documents(assigned_lawyer_id);

create table document_versions (
  id uuid primary key default gen_random_uuid(),
  document_id uuid not null references documents(id) on delete cascade,
  version_no integer not null check (version_no > 0),
  storage_key text not null,               -- S3/R2 or Supabase Storage object key, never file bytes
  created_at timestamptz not null default now(),
  unique (document_id, version_no)
);

-- Versions are immutable: new revision = new row
create trigger document_versions_no_update
before update on document_versions
for each row execute function reject_modification();

create index document_versions_document_id_idx on document_versions(document_id);
