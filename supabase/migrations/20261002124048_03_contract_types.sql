create type contract_type_status as enum ('planned', 'in_build', 'validated', 'live');

create table contract_types (
  code text primary key,
  display_name text not null,
  display_name_i18n jsonb not null default '{}'::jsonb,
  category text not null check (category in (
    'commercial_sales', 'corporate_confidentiality', 'hr_employment',
    'financial_investment', 'real_estate_leases'
  )),
  status contract_type_status not null default 'planned',
  created_at timestamptz not null default now()
);

insert into contract_types (code, display_name, category) values
  ('vendor_supplier', 'Vendor / Supplier Agreement', 'commercial_sales'),
  ('sla', 'Service Level Agreement (SLA)', 'commercial_sales'),
  ('msa', 'Master Services Agreement (MSA)', 'commercial_sales'),
  ('distributor_dealership', 'Distributor / Dealership Agreement', 'commercial_sales'),
  ('nda', 'Non-Disclosure Agreement (NDA)', 'corporate_confidentiality'),
  ('founders_agreement', 'Co-Founder / Founders'' Agreement', 'corporate_confidentiality'),
  ('partnership_deed', 'Partnership Deed', 'corporate_confidentiality'),
  ('jva', 'Joint Venture Agreement (JVA)', 'corporate_confidentiality'),
  ('employment_contract', 'Employment Contract / Appointment Letter', 'hr_employment'),
  ('consultant_freelancer', 'Independent Consultant / Freelancer Agreement', 'hr_employment'),
  ('non_compete_non_solicit', 'Non-Compete & Non-Solicitation Agreement', 'hr_employment'),
  ('esop', 'Employee Stock Option Plan (ESOP) Agreement', 'hr_employment'),
  ('sha', 'Shareholders'' Agreement (SHA)', 'financial_investment'),
  ('term_sheet_investment', 'Term Sheet / Investment Agreement', 'financial_investment'),
  ('loan_debt', 'Loan / Debt Agreement', 'financial_investment'),
  ('intercreditor_hypothecation', 'Inter-creditor / Hypothecation Agreement', 'financial_investment'),
  ('commercial_lease', 'Commercial Lease / Rental Agreement', 'real_estate_leases'),
  ('leave_and_license', 'Leave and License Agreement', 'real_estate_leases'),
  ('equipment_lease', 'Equipment Lease Agreement', 'real_estate_leases');

-- The 4 types in the SRD are the first to be built
update contract_types set status = 'in_build'
where code in ('nda', 'vendor_supplier', 'founders_agreement', 'sha');
