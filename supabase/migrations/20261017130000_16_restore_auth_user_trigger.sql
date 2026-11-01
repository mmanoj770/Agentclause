-- Migration 02's trigger lives in the auth schema, which the project move skipped:
-- recreate it so new sign-ups get a profile row again.
drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
after insert on auth.users
for each row execute function public.handle_new_user();

-- Backfill: any auth user created while the trigger was missing has no profile, and then gets
-- a token without role or org. Create the same row handle_new_user would have created:
-- (id, email, full_name from raw_user_meta_data), with role and org_id left to the column
-- defaults (startup_user, null). Role and org are never read from user or app metadata.
-- Idempotent: users that already have a profile are skipped, and re-running inserts nothing.
do $$
declare
  u record;
begin
  for u in
    select au.id, au.email, au.raw_user_meta_data ->> 'full_name' as full_name
    from auth.users au
    where not exists (select 1 from public.profiles p where p.id = au.id)
  loop
    insert into public.profiles (id, email, full_name)
    values (u.id, u.email, u.full_name)
    on conflict (id) do nothing;
    if found then
      raise notice 'backfilled profile for user %', u.id;
    end if;
  end loop;
end
$$;
