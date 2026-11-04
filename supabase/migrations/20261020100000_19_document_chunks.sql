-- Migration 19: document_chunks, the clause-level pieces of an uploaded contract version and their embeddings.
-- NOT APPLIED. Needs review before any push (team rule: nobody pushes SQL that hasn't been seen).
-- Run scripts/preflight_19.sql first, and take a fresh backup (as for migration 18).
--
-- Design notes:
--   * Chunks belong to a document_version, not just a document: versions are immutable (migration 04),
--     so a revision gets its own chunks and retrieval never mixes text from two versions.
--     document_id is kept alongside for tenancy checks without a join; a trigger keeps it consistent
--     with the version.
--   * embedding is vector(768) to match clauses.embedding, since chunks are compared against clauses.
--   * Tracking columns match clauses (migration 14): which model embedded the row, at which version,
--     and a hash of the exact text. Nullable with no default: the embed job sets them from
--     settings.gemini_embedding_model (gemini.py: never hard-code a model name elsewhere).
--   * hnsw instead of ivfflat: ivfflat built on an empty table gives poor recall; hnsw needs no
--     training data.
--   * RLS enabled with no policy and no grants: chunks are read only by the backend, through
--     app.documents.chunk_service, which does the org / assignment checks. verify_grants.sql
--     expects exactly this (no client privileges on a table without a SELECT policy).

create table document_chunks (
  id uuid primary key default gen_random_uuid(),
  document_id uuid not null references documents(id) on delete cascade,
  document_version_id uuid not null references document_versions(id) on delete cascade,
  chunk_index int not null check (chunk_index >= 0),
  clause_number text,
  heading text,
  text text not null,
  embedding vector(768),
  embedding_model    text,
  embedded_version   integer,
  embedded_text_hash text,
  created_at timestamptz not null default now(),
  unique (document_version_id, chunk_index)
);

comment on table document_chunks is
  'Clause-level chunks of a document version, with embeddings for retrieval. Backend (service role) only.';
comment on column document_chunks.embedding is
  'Same dimensions and model as clauses.embedding, so the two can be compared.';

-- A chunk's document_id must be the document its version belongs to.
create function document_chunks_check_document()
returns trigger language plpgsql as $$
begin
  if not exists (select 1 from document_versions v
                 where v.id = new.document_version_id and v.document_id = new.document_id) then
    raise exception 'document_chunks: version % does not belong to document %',
      new.document_version_id, new.document_id;
  end if;
  return new;
end;
$$;

create trigger document_chunks_check_document
before insert or update of document_id, document_version_id on document_chunks
for each row execute function document_chunks_check_document();

-- The unique (document_version_id, chunk_index) index already serves lookups by version.
create index document_chunks_document_id_idx on document_chunks (document_id);
create index document_chunks_embedding_idx on document_chunks using hnsw (embedding vector_cosine_ops);

alter table document_chunks enable row level security;
revoke all on table document_chunks from anon, authenticated;
revoke all on function document_chunks_check_document() from public, anon, authenticated;
