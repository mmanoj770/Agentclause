-- Finding Schema (R1): store the legal citation behind each finding.
-- Nullable: existing rows and lawyer-added findings have none.
alter table findings add column citation text;

-- Review status, derived from advocate_action so the two can never disagree.
alter table findings add column status text generated always as (
  case advocate_action
    when 'confirm' then 'confirmed'
    when 'override' then 'overridden'
    when 'add' then 'added'
    else 'pending'
  end
) stored;

create index findings_status_idx on findings(status);
