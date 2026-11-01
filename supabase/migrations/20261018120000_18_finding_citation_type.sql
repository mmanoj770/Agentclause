-- Migration 18: findings.citation_type (Layer 5 citation gate, item 3).
--
-- What this does
--   1. Adds findings.citation_type: STATUTORY | CASE | CORPUS | INTERNAL_BASELINE.
--   2. Backfills existing findings that already have a citation (rules below).
--   3. Closes the NOT NULL mismatch between the Finding model and the table: the model requires a
--      citation, but migration 11 left findings.citation nullable. After this migration, every
--      finding that is not lawyer-added must carry a citation AND a citation_type. Lawyer-added
--      findings (advocate_action = 'add') may carry neither.
--
-- What this does NOT do
--   * It does not decide whether a citation is real. That is the gate's job at write time
--     (STATUTORY and CASE must resolve to the corpus; an "Internal:" prefix decides nothing).
--   * It does not touch rule_applied, clause_reference or remedy_suggested (also nullable in the
--     table, required in the model). Out of scope for item 3.
--   * It does not touch clauses migrations 11-14 or any index.
--
-- Backfill rules (existing rows only; the gate never reads these rules)
--   citation is null                                     -> citation_type stays null
--   citation looks like "<Name>, <year>, s. <n>"         -> STATUTORY
--   citation starts with "Internal:"                     -> INTERNAL_BASELINE
--   any other non-null citation                          -> the migration ABORTS (nothing is guessed)
-- Rows written before the gate existed were never gate-checked. Their label records what kind of
-- source the string names, not that it was verified.
--
-- Abort conditions (the whole migration rolls back; nothing is half-applied)
--   * a non-null citation matches neither backfill rule
--   * a non-lawyer-added finding has a null or blank citation
-- Run scripts/preflight_18.sql (read-only) before the push to see both counts.
--
-- Rollback (manual, only if needed):
--   alter table findings drop constraint findings_agent_citation_required,
--                        drop constraint findings_citation_not_blank,
--                        drop constraint findings_citation_pairing,
--                        drop constraint findings_citation_type_check;
--   alter table findings drop column citation_type;

alter table findings add column citation_type text;

update findings
set citation_type = case
      when citation ~ '^.+,\s*\d{4},\s*(s|ss)\.\s*\d' then 'STATUTORY'
      when citation ~ '^Internal:'                     then 'INTERNAL_BASELINE'
    end
where citation is not null
  and citation_type is null;

do $$
declare
  n_unclassified integer;
  n_uncited      integer;
begin
  select count(*) into n_unclassified
  from findings
  where citation is not null and citation_type is null;
  if n_unclassified > 0 then
    raise exception 'migration 18 aborted: % finding(s) have a citation the backfill cannot classify', n_unclassified;
  end if;

  select count(*) into n_uncited
  from findings
  where coalesce(advocate_action, '') <> 'add'
    and (citation is null or btrim(citation) = '');
  if n_uncited > 0 then
    raise exception 'migration 18 aborted: % non-lawyer-added finding(s) have no citation', n_uncited;
  end if;
end
$$;

alter table findings
  add constraint findings_citation_type_check
    check (citation_type in ('STATUTORY', 'CASE', 'CORPUS', 'INTERNAL_BASELINE')),
  -- a citation and its type always travel together
  add constraint findings_citation_pairing
    check ((citation is null) = (citation_type is null)),
  add constraint findings_citation_not_blank
    check (citation is null or btrim(citation) <> ''),
  -- coalesce: a null advocate_action (agent finding awaiting review) must not make the check pass by accident
  add constraint findings_agent_citation_required
    check (coalesce(advocate_action, '') = 'add' or citation is not null);
