create table findings (
  id uuid primary key default gen_random_uuid(),
  document_id uuid not null references documents(id) on delete cascade,
  document_version_id uuid not null references document_versions(id) on delete cascade,
  layer smallint not null check (layer between 0 and 6),
  severity text not null check (severity in ('low', 'medium', 'high', 'critical')),
  clause_reference text,
  description text not null,
  rule_applied text,                       -- visible rule ID, e.g. 'ICA_S27_NON_COMPETE'
  remedy_suggested text,
  advocate_action text check (advocate_action in ('confirm', 'override', 'add')),
  advocate_notes text,
  adjudicated_by uuid references profiles(id) on delete set null,
  adjudicated_at timestamptz,
  created_at timestamptz not null default now()
);

create index findings_document_id_idx on findings(document_id);
create index findings_layer_idx on findings(layer);
create index findings_severity_idx on findings(severity);

create table lawyer_assignments (
  id uuid primary key default gen_random_uuid(),
  document_id uuid not null unique references documents(id) on delete cascade,
  lawyer_id uuid not null references profiles(id) on delete restrict,
  assigned_at timestamptz not null default now(),  -- the moment the lawyer claimed it from the queue
  signed_off_at timestamptz                        -- null until sign-off
);

create index lawyer_assignments_lawyer_id_idx on lawyer_assignments(lawyer_id);
