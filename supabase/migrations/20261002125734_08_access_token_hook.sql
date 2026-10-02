create function public.custom_access_token_hook(event jsonb)
returns jsonb
language plpgsql
stable
as $$
declare
  claims jsonb;
  p_role public.user_role;
  p_org uuid;
begin
  select role, org_id into p_role, p_org
  from public.profiles
  where id = (event ->> 'user_id')::uuid;

  claims := event -> 'claims';

  if p_role is not null then
    claims := jsonb_set(claims, '{user_role}', to_jsonb(p_role));
    claims := jsonb_set(claims, '{org_id}', coalesce(to_jsonb(p_org), 'null'::jsonb));
  end if;

  return jsonb_set(event, '{claims}', claims);
end;
$$;

-- Only Supabase Auth may run this hook
grant usage on schema public to supabase_auth_admin;
grant execute on function public.custom_access_token_hook to supabase_auth_admin;
revoke execute on function public.custom_access_token_hook from authenticated, anon, public;

-- The hook reads profiles, so Auth needs permission past RLS
grant select on table public.profiles to supabase_auth_admin;
create policy profiles_auth_admin_read on public.profiles
  as permissive for select to supabase_auth_admin using (true);
