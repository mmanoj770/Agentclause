create extension if not exists vector;

create type user_role as enum ('startup_user', 'lawyer');

create type document_state as enum (
  'drafted',
  'under_ai_review',
  'pending_lawyer_review',
  'lawyer_commented',
  'revision_in_progress',
  'lawyer_approved',
  'delivered',
  'negotiation_in_progress'
);
