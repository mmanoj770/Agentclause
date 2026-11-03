-- Migration 20: document_chunks.section_kind (R8 #7 clause manifest per version).
-- Applied to live on 2026-11-03.
-- Allows distinguishing clause sections (body, schedule, annexure) for manifest checks.

alter table public.document_chunks
  add column if not exists section_kind text not null default 'body';

alter table public.document_chunks
  add constraint document_chunks_section_kind_check
  check (section_kind in ('body', 'schedule', 'annexure'));
