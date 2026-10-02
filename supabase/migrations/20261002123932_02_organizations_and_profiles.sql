create table organizations (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  gstin text,
  msme_registered boolean not null default false,
  created_at timestamptz not null default now()
);

create table profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  role user_role not null default 'startup_user',
  full_name text,
  email text,
  org_id uuid references organizations(id) on delete set null,
  created_at timestamptz not null default now(),
  -- lawyers belong to the professional entity, not a client org
  constraint lawyer_has_no_org check (role <> 'lawyer' or org_id is null)
);

create index profiles_org_id_idx on profiles(org_id);
create index profiles_role_idx on profiles(role);

-- Auto-create a profile whenever someone signs up
create function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  insert into public.profiles (id, email, full_name)
  values (new.id, new.email, new.raw_user_meta_data ->> 'full_name');
  return new;
end;
$$;

create trigger on_auth_user_created
after insert on auth.users
for each row execute function public.handle_new_user();
