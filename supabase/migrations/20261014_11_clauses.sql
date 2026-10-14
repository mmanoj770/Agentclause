create type verification_status as enum ('staging', 'verified');
create type favoured_party     as enum ('party_a', 'party_b', 'neutral');

create table clauses (
  clause_id           uuid primary key default gen_random_uuid(),

  -- D1 metadata
  clause_type         text not null,           -- e.g. 'indemnity', 'nda_scope', 'payment_terms'
  contract_types      text[] not null,         -- matches codes in contract_types table e.g. ['nda', 'vendor_supplier']
  favoured_party      favoured_party not null,
  statute_refs        text[] not null default '{}',  -- e.g. ['ICA_s27', 'MSMED_s15']
  version             integer not null default 1,

  -- The tier separator: this is what D2 is about
  verification_status verification_status not null default 'staging',

  -- Content
  content             text not null,
  title               text not null,
  notes               text,

  -- Audit trail for verification
  verified_by         text,                    -- advocate name/ID who cleared it
  verified_at         timestamptz,             -- set automatically when status = 'verified'
  created_at          timestamptz not null default now()
);

-- D4 (retrieval) will filter heavily on these
create index clauses_type_idx      on clauses(clause_type);
create index clauses_status_idx    on clauses(verification_status);
create index clauses_contracts_idx on clauses using gin(contract_types);

-- D3 will add this column once the embedding pipeline is ready:
-- alter table clauses add column embedding vector(1536);

-- RLS: same pattern as every other table — read-only for authenticated, all writes through FastAPI
alter table clauses enable row level security;
revoke insert, update, delete on clauses from anon, authenticated;
create policy clauses_read on clauses
  for select to authenticated using (true);
