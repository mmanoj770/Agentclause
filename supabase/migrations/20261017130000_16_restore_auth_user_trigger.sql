-- Migration 02's trigger lives in the auth schema, which the project move skipped:
-- recreate it so new sign-ups get a profile row again.
drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
after insert on auth.users
for each row execute function public.handle_new_user();
