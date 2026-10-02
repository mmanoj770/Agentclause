-- When a document entered the queue (gives a fair, same-for-everyone order)
alter table documents add column queued_at timestamptz;
update documents set queued_at = updated_at where state = 'pending_lawyer_review';

create index documents_queue_idx on documents (queued_at, id)
  where state = 'pending_lawyer_review' and assigned_lawyer_id is null;

-- Conflicts a lawyer has declared against a client org
create table lawyer_conflicts (
  id uuid primary key default gen_random_uuid(),
  lawyer_id uuid not null references profiles(id) on delete cascade,
  org_id uuid not null references organizations(id) on delete cascade,
  reason text,
  created_at timestamptz not null default now(),
  unique (lawyer_id, org_id)
);

alter table lawyer_conflicts enable row level security;
revoke insert, update, delete on lawyer_conflicts from anon, authenticated;
create policy lawyer_conflicts_read on lawyer_conflicts
  for select to authenticated using (lawyer_id = auth.uid());
