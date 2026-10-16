-- D3/D4: keep clause embeddings in sync with clause text.
-- When a clause's title or content changes, its old embedding no longer describes it.
-- Reset it to NULL so `python -m app.clauses.embed_runner` re-embeds exactly the changed clauses.
-- (Note: uses a full 14-digit timestamp prefix; Supabase treats the leading digits as the
-- migration version, so two files may not share the same prefix.)

create or replace function clauses_reset_stale_embedding()
returns trigger
language plpgsql
as $$
begin
  if new.content is distinct from old.content
     or new.title is distinct from old.title then
    new.embedding := null;
  end if;
  return new;
end;
$$;

create trigger clauses_reset_stale_embedding
  before update on clauses
  for each row
  execute function clauses_reset_stale_embedding();
