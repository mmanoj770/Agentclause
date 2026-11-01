-- D3: make the embedding job model- and version-aware.
-- Each clause records which model embedded it, at which clause version, and a hash of
-- the exact text embedded. The job (python -m app.clauses.embed_runner) skips a clause
-- only when all three still match, and re-embeds it otherwise.

alter table clauses
  add column embedding_model    text,
  add column embedded_version   integer,
  add column embedded_text_hash text;

-- Extend migration 13's trigger: a change to title, content OR version makes the
-- stored embedding stale, so clear the vector immediately (retrieval never ranks a
-- clause without a current embedding). The tracking columns are kept as a record of
-- what was last embedded, so the job can log WHY it re-embeds the clause.
create or replace function clauses_reset_stale_embedding()
returns trigger
language plpgsql
as $$
begin
  if new.content is distinct from old.content
     or new.title is distinct from old.title
     or new.version is distinct from old.version then
    new.embedding := null;
  end if;
  return new;
end;
$$;

-- The placeholder clause formerly seeded as 'nda_scope' is now 'confidentiality'.
-- Rename it in place (staging rows only) so re-seeding does not create a duplicate.
update clauses
   set clause_type = 'confidentiality',
       title = 'Confidentiality Obligation [PLACEHOLDER]'
 where clause_type = 'nda_scope'
   and title = 'Standard NDA Scope [PLACEHOLDER]'
   and verification_status = 'staging';
