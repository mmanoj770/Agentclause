create table audit_logs (
  id bigint generated always as identity primary key,
  document_id uuid,        -- no foreign keys on purpose, so history survives deletions
  actor_id uuid,
  actor_role text,         -- snapshot of the role at the time
  action text not null,    -- e.g. 'state_change', 'finding_adjudicated', 'sign_off'
  details jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index audit_logs_document_id_idx on audit_logs(document_id);
create index audit_logs_created_at_idx on audit_logs(created_at);

-- Append-only, enforced two ways
create trigger audit_logs_no_update_delete
before update or delete on audit_logs
for each row execute function reject_modification();

create trigger audit_logs_no_truncate
before truncate on audit_logs
for each statement execute function reject_modification();

revoke update, delete, truncate on audit_logs from anon, authenticated, service_role;
