-- Migration 19: document_chunks, the clause-level pieces of an uploaded contract and their embeddings.
-- NOT APPLIED. Needs review before any push (team rule: nobody pushes SQL that hasn't been seen).
--
-- Differences from the requested SQL, and why:
--   * embedding is vector(768), not 1536: clauses.embedding (migration 12) is vector(768) from
--     Gemini text-embedding-004, and chunks are compared against clauses, so the sizes must match.
--   * hnsw instead of ivfflat: ivfflat built on an empty table gives poor recall (the warning
--     migration 12 printed); hnsw needs no training data. pgvector on live is 0.8.2.
--   * created_at is timestamptz not null, like every other table here.
--   * RLS enabled with no policy and no grants: chunks are read by the backend only (same stance
--     as clauses), and verify_grants.sql expects no client privileges without a SELECT policy.

create table document_chunks (
  id uuid primary key default gen_random_uuid(),
  document_id uuid not null references documents(id) on delete cascade,
  chunk_index int not null check (chunk_index >= 0),
  clause_number text,
  heading text,
  text text not null,
  embedding vector(768),
  created_at timestamptz not null default now(),
  unique (document_id, chunk_index)
);

-- The unique (document_id, chunk_index) index already serves lookups by document_id.
create index document_chunks_embedding_idx on document_chunks using hnsw (embedding vector_cosine_ops);

alter table document_chunks enable row level security;
revoke all on table document_chunks from anon, authenticated;
