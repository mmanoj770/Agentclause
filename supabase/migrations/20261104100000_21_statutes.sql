-- 21: statutes (R8 #3). Table only; no data.
create extension if not exists btree_gist;

create table public.statutes (
  id               uuid primary key default gen_random_uuid(),
  act              text not null,
  section          text not null,
  heading          text,
  statute_text     text not null,
  source_url       text,
  effective_from   date not null,
  effective_to     date,
  status           verification_status not null default 'staging',
  verified_by      text,
  verified_at      timestamptz,
  verification_ref text,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now(),
  constraint statutes_effective_range_check
    check (effective_to is null or effective_to > effective_from),
  constraint statutes_verified_needs_evidence_check
    check (status <> 'verified'
           or (verified_by is not null and verified_at is not null and verification_ref is not null)),
  constraint statutes_act_section_from_key unique (act, section, effective_from),
  constraint statutes_no_overlap
    exclude using gist (act with =, section with =,
                        daterange(effective_from, effective_to, '[)') with &&)
);

create trigger statutes_set_updated_at
before update on public.statutes
for each row execute function set_updated_at();

alter table public.statutes enable row level security;
revoke all on public.statutes from anon, authenticated, public;
