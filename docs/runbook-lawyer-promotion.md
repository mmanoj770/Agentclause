# Runbook: promoting a user to lawyer

**Lawyer promotion happens only by hand, with a service-role (admin) update. There is no self-service path, and there must never be one.**

Why: `profiles.role` decides who sees the review queue and other clients' unclaimed documents, who can adjudicate findings, and who can sign off a document. A sign-up flow, an API route or a client-side write that could set it would let anyone make themselves a lawyer. The database enforces this too: `anon` and `authenticated` hold no write privilege on `profiles` (see `scripts/verify_grants.sql`), and `handle_new_user` never reads a role from user metadata. A new account is always `startup_user` with no org.

## Steps

1. The person signs up normally. The `on_auth_user_created` trigger creates their `profiles` row as `startup_user`, `org_id` null.
2. Confirm the right account (check the email against `auth.users`) and get their user id.
3. Run, as the service role / database owner (never from the app):

   ```sql
   update public.profiles set role = 'lawyer', org_id = null where id = '<user id>';
   ```

   Lawyers belong to the professional entity, not a client org, so `org_id` must be null. The `lawyer_has_no_org` constraint (`role <> 'lawyer' or org_id is null`) rejects a lawyer who still has an org, which is why the same statement clears it.
4. Record it in `audit_logs`, in the same transaction as the update. The table is append-only and nothing in the app writes this event, so insert it by hand:

   ```sql
   insert into public.audit_logs (document_id, actor_id, actor_role, action, details)
   values (null, null, 'service_role', 'lawyer_promoted',
           jsonb_build_object('user_id', '<user id>', 'promoted_by', '<your name or id>', 'reason', '<why>'));
   ```
5. Ask the user to sign out and back in. The role and org are copied into the access token when it is issued (`custom_access_token_hook`), so an existing token keeps the old role until it is refreshed.

To demote or move someone, do the same in reverse: a hand update plus an `audit_logs` row.
