-- Re-apply migration 08's revoke: it was lost when the database moved to the new project,
-- leaving the hook callable via /rest/v1/rpc by anon and authenticated users
-- (it returns any user's role and org_id).
revoke execute on function public.custom_access_token_hook(jsonb) from authenticated, anon, public;
