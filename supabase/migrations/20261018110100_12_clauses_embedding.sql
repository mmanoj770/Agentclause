-- D3: add pgvector embedding column to clauses table
-- Uses 768 dimensions to match Google Gemini text-embedding-004 model
-- pgvector extension already enabled in migration 01

alter table clauses add column embedding vector(768);

-- ivfflat index for fast cosine similarity search (D4 retrieval)
-- lists=10 is appropriate for small datasets (our ~5-100 clause range)
create index clauses_embedding_idx
  on clauses
  using ivfflat (embedding vector_cosine_ops)
  with (lists = 10);
