"""Full-lifecycle dry run against the REAL project: the Monday-night checklist, as a script.

    cd backend && python ../scripts/dry_run.py [--base-url http://127.0.0.1:8000]

One document walks the whole path with real accounts: startup user A uploads a contract, requests the
stub review (Layer 5 gate), the lawyer claims it from the queue, adds a finding, adjudicates, signs off;
startup A then reads the client view and chats; startup B is shown to see nothing throughout.

Needs migration 18 applied (it checks first and stops with a clear message if not), and these in the
environment or in .env.local: SUPABASE_URL, SUPABASE_ANON_KEY, DATABASE_URL, the S3 settings,
TEST_USER_EMAIL / TEST_USER_PASSWORD (startup A), TEST_USER_B_EMAIL / TEST_USER_B_PASSWORD (startup B,
another org), TEST_LAWYER_EMAIL / TEST_LAWYER_PASSWORD (a lawyer who has no conflict with A's org).

Prints PASS/FAIL per step and never prints tokens, passwords or keys. Deletes NOTHING: the document, its
version, the S3 object, the findings and the audit rows stay, and their ids are printed at the end so the
Thursday cleanup can list them explicitly. Reuses the helpers in e2e_upload.py.
"""
import argparse
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import e2e_upload as e2e  # noqa: E402  (also puts backend/ on sys.path and loads .env.local)
import httpx  # noqa: E402
from pydantic_settings import BaseSettings, SettingsConfigDict  # noqa: E402

from app.config import ROOT  # noqa: E402

report, skip, detail = e2e.report, e2e.skip, e2e.api_detail
CLIENT_KEYS = {"finding_id", "id", "severity", "clause_reference", "description", "remedy_suggested",
               "citation", "citation_type", "status", "origin"}
REVIEW_TIMEOUT_S = 180   # the R10 pipeline runs in the background; poll the document state until then
HIDDEN_FROM_CLIENT = ("layer", "rule_applied", "advocate_notes", "adjudicated_by", "adjudicated_at")


class LawyerEnv(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env.local", extra="ignore")

    test_lawyer_email: str = ""
    test_lawyer_password: str = ""


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def sign_in_all():
    lawyer_env = LawyerEnv()
    need = (("TEST_USER_EMAIL", e2e.env.test_user_email), ("TEST_USER_PASSWORD", e2e.env.test_user_password),
            ("TEST_USER_B_EMAIL", e2e.env.test_user_b_email), ("TEST_USER_B_PASSWORD", e2e.env.test_user_b_password),
            ("TEST_LAWYER_EMAIL", lawyer_env.test_lawyer_email),
            ("TEST_LAWYER_PASSWORD", lawyer_env.test_lawyer_password),
            ("SUPABASE_ANON_KEY", e2e.env.supabase_anon_key))
    missing = [n for n, v in need if not v]
    if not report("0", "all accounts configured", not missing, "missing: " + ", ".join(missing) if missing else ""):
        return None
    tokens = {}
    for who, email, password in (("startup A", e2e.env.test_user_email, e2e.env.test_user_password),
                                 ("startup B", e2e.env.test_user_b_email, e2e.env.test_user_b_password),
                                 ("lawyer", lawyer_env.test_lawyer_email, lawyer_env.test_lawyer_password)):
        token = e2e.password_grant("0", f"sign in as {who}", email, password)
        if token is None:
            return None
        report("0", f"sign in as {who}", True)
        tokens[who] = token
    roles = {w: (e2e.unverified_claims(t).get("user_role"), e2e.unverified_claims(t).get("org_id"))
             for w, t in tokens.items()}
    ok = (roles["startup A"][0] == "startup_user" and roles["startup B"][0] == "startup_user"
          and roles["lawyer"][0] == "lawyer" and roles["startup A"][1] and roles["startup B"][1]
          and roles["startup A"][1] != roles["startup B"][1])
    if not report("0", "roles: A and B are startup users in different orgs, the lawyer is a lawyer", bool(ok),
                  ", ".join(f"{w}={r[0]}" for w, r in roles.items())):
        return None
    return tokens


def migration_18_applied() -> bool:
    rows = e2e.db_rows("select 1 from information_schema.columns where table_schema = 'public' "
                       "and table_name = 'findings' and column_name = 'citation_type'", ())
    return report("0", "migration 18 is applied (findings.citation_type exists)", len(rows) == 1,
                  "" if rows else "STOP: apply migration 18 first; a review would fail on the insert")


def queue_ids(client, auth) -> set[str]:
    r = client.get("/queue", params={"limit": 100}, headers=auth)
    return {d["id"] for d in r.json()} if r.status_code == 200 else set()


def run(client, tokens: dict, ctx: dict) -> None:
    a, b, law = bearer(tokens["startup A"]), bearer(tokens["startup B"]), bearer(tokens["lawyer"])
    if not migration_18_applied():
        return

    # 1. startup A uploads a contract
    made = e2e.upload_new_document(client, a, "1", "A")
    if made is None:
        return
    doc, key = made
    ctx.update(document_id=doc, s3_key=key)
    print(f"      document id: {doc}")

    # 2. not in the lawyer queue yet; startup B cannot see it
    report("2", "a drafted document is not in the lawyer queue", doc not in queue_ids(client, law))
    r = client.get(f"/documents/{doc}", headers=b)
    report("2", "startup B cannot open A's document (404)", r.status_code == 404, detail(r))

    # 3. the AI review (R10 pipeline, in the background), through the Layer 5 gate
    r = client.post(f"/documents/{doc}/review", headers=a)
    if not report("3", "review -> 202, under_ai_review", r.status_code == 202
                  and r.json().get("state") == "under_ai_review", detail(r)):
        return
    state, waited = "under_ai_review", 0.0
    while state == "under_ai_review" and waited < REVIEW_TIMEOUT_S:
        time.sleep(1.0)
        waited += 1.0
        state = (client.get(f"/documents/{doc}", headers=a).json() or {}).get("state")
    rows = e2e.audit_rows(doc)
    failed = [x for x in rows if x["action"] == "ai_review_failed"]
    if not report("3", "the pipeline finished: pending_lawyer_review", state == "pending_lawyer_review",
                  f"state {state} after {waited:.0f}s" + (f"; failed in {failed[-1]['details'].get('layer')} "
                                                          f"({failed[-1]['details'].get('error_type')})" if failed else "")):
        return
    created_rows = [x for x in rows if x["action"] == "findings_created"]
    created = created_rows[-1]["details"].get("count", 0) if created_rows else 0
    blocked = sum(1 for x in rows if x["action"] == "citation_blocked")
    # Strict mode is the production default: while every rule is unverified, 0 findings is the expected answer.
    report("3", "findings_created recorded (0 is expected while every rule is unverified)", bool(created_rows),
           f"stored {created}, blocked {blocked}")

    # 4. before sign-off the client view refuses, and shows nothing
    r = client.get(f"/documents/{doc}/client-findings", headers=a)
    report("4", "client findings before sign-off -> 409", r.status_code == 409, detail(r))

    # 5. the lawyer finds it in the queue and claims it
    report("5", "the document is in the lawyer queue", doc in queue_ids(client, law))
    r = client.post(f"/queue/{doc}/claim", headers=law)
    if not report("5", "lawyer claims it", r.status_code == 200, detail(r)):
        return
    report("5", "it has left the queue", doc not in queue_ids(client, law))
    r = client.get(f"/documents/{doc}/client-findings", headers=b)
    report("5", "startup B still cannot reach it (404)", r.status_code == 404, detail(r))

    # 6. the lawyer's merged findings list
    r = client.get(f"/documents/{doc}/findings", headers=law)
    items = r.json() if r.status_code == 200 else []
    report("6", "lawyer lists the findings", r.status_code == 200 and len(items) == created,
           detail(r) if r.status_code != 200 else f"{len(items)} item(s)")
    report("6", "all are origin=agent, with finding_id == id, a layer name and a citation_type",
           all(i["origin"] == "agent" and i["id"] == i["finding_id"] and i["layer"] and i["citation_type"]
               for i in items))
    open_serious = [i for i in items if i["severity"] in ("high", "critical")]

    # 7. sign-off is refused while a high or critical finding is undecided
    if open_serious:
        r = client.post(f"/documents/{doc}/transition", headers=law, json={"to_state": "lawyer_approved"})
        report("7", "approve with open high/critical findings -> 409", r.status_code == 409, detail(r))
    else:
        skip("7", "approve is refused while high/critical findings are open", "no high/critical finding")

    # 8. the lawyer adds a finding of their own
    r = client.post(f"/documents/{doc}/findings", headers=law,
                    json={"severity": "medium", "description": "Dry-run lawyer-added finding",
                          "clause_reference": "Clause 9", "notes": "private lawyer note"})
    added = r.json() if r.status_code == 201 else {}
    report("8", "lawyer adds a finding -> 201, origin=advocate, no layer or citation",
           r.status_code == 201 and added.get("origin") == "advocate" and "layer" not in added
           and "citation" not in added, detail(r))
    r = client.get(f"/documents/{doc}/findings", headers=law)
    merged = r.json() if r.status_code == 200 else []
    report("8", "the merged list has the agent findings plus the added one",
           len(merged) == created + 1 and sum(1 for i in merged if i["origin"] == "advocate") == 1,
           f"{len(merged)} item(s)")

    # 9. adjudicate: confirm all but the last agent finding, override the last
    agent = [i for i in merged if i["origin"] == "agent"]
    confirmed, overridden = agent[:-1], agent[-1:]
    if added:
        r = client.post(f"/findings/{added['finding_id']}/adjudicate", headers=law, json={"action": "confirm"})
        report("9", "a lawyer-added finding cannot be adjudicated (409)", r.status_code == 409, detail(r))
    if overridden:
        r = client.post(f"/findings/{overridden[0]['finding_id']}/adjudicate", headers=law,
                        json={"action": "override"})
        report("9", "override without a reason -> 422", r.status_code == 422, detail(r))
    ok = True
    for f in confirmed:
        r = client.post(f"/findings/{f['finding_id']}/adjudicate", headers=law, json={"action": "confirm"})
        ok &= r.status_code == 200 and r.json().get("status") == "confirmed"
    for f in overridden:
        r = client.post(f"/findings/{f['finding_id']}/adjudicate", headers=law,
                        json={"action": "override", "notes": "dry run: not applicable"})
        ok &= r.status_code == 200 and r.json().get("status") == "overridden"
    report("9", f"{len(confirmed)} confirmed, {len(overridden)} overridden", ok)

    # 10. sign-off
    r = client.post(f"/documents/{doc}/transition", headers=law, json={"to_state": "lawyer_approved"})
    if not report("10", "lawyer signs off -> lawyer_approved", r.status_code == 200
                  and r.json().get("state") == "lawyer_approved", detail(r)):
        return

    # 11. the client view after sign-off
    r = client.get(f"/documents/{doc}/client-findings", headers=a)
    view = r.json() if r.status_code == 200 else []
    if report("11", "client findings after sign-off -> 200", r.status_code == 200, detail(r)):
        want = {f["finding_id"] for f in confirmed} | ({added["finding_id"]} if added else set())
        report("11", "exactly the confirmed and lawyer-added findings (no overridden, no pending)",
               {v["finding_id"] for v in view} == want, f"{len(view)} shown, {len(want)} expected")
        report("11", "origins are right and id == finding_id",
               all(v["id"] == v["finding_id"] and v["origin"] == ("advocate" if added and v["finding_id"]
                   == added["finding_id"] else "agent") for v in view))
        report("11", "no layer, rule ID, lawyer notes or adjudication data reach the client",
               all(set(v) == CLIENT_KEYS and not any(h in v for h in HIDDEN_FROM_CLIENT) for v in view)
               and "private lawyer note" not in r.text)
    r = client.get(f"/documents/{doc}/client-findings", headers=b)
    report("11", "startup B still cannot see it (404)", r.status_code == 404, detail(r))

    # 12. the client's own views, then chat
    r = client.get(f"/documents/{doc}", headers=a)
    report("12", "document shows lawyer_approved to its owner", r.status_code == 200
           and r.json().get("state") == "lawyer_approved", detail(r))
    r = client.get("/documents", headers=a)
    report("12", "it is in A's document list", r.status_code == 200 and any(d["id"] == doc for d in r.json()))
    r = client.post(f"/documents/{doc}/chat", headers=a, json={"question": "How long does the agreement last?"})
    report("12", "chat -> 200 with a status", r.status_code == 200 and r.json().get("status") in
           ("answered", "refused", "escalated"), detail(r) if r.status_code != 200 else r.json()["status"])

    # 13. delivered: the state machine lets only the system make this move, and no route does
    r = client.post(f"/documents/{doc}/transition", headers=law, json={"to_state": "delivered"})
    report("13", "a lawyer cannot mark it delivered (403: system-only move)", r.status_code == 403, detail(r))
    print("      NOTE: nothing in the API moves lawyer_approved -> delivered. The client view and chat both work at "
          "lawyer_approved, and the frontend treats both as settled, but a decision is needed for the demo.")

    # 14. the audit trail tells the whole story
    actions = [x["action"] for x in e2e.audit_rows(doc)]
    need = ["document_created", "file_uploaded", "findings_created", "document_claimed", "finding_added",
            "finding_adjudicated", "state_change", "chat_turn"]
    report("14", "audit trail has every step", all(n in actions for n in need),
           "missing: " + ", ".join(n for n in need if n not in actions) if not all(n in actions for n in need) else "")
    report("14", "finding_adjudicated rows match the decisions made",
           actions.count("finding_adjudicated") == len(confirmed) + len(overridden),
           f"{actions.count('finding_adjudicated')} logged")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", help="use a running server instead of running the app in-process")
    args = ap.parse_args()
    print(f"settings file: {'found' if (ROOT / '.env.local').exists() else 'NOT FOUND'} (.env.local)")
    tokens = sign_in_all()
    if tokens is None:
        return 1
    ctx: dict = {}
    try:
        from app.db import pool
        if args.base_url:
            pool.open()
            try:
                with httpx.Client(base_url=args.base_url, timeout=60) as client:
                    run(client, tokens, ctx)
            finally:
                pool.close()
        else:
            from fastapi.testclient import TestClient
            from app.main import app
            with TestClient(app) as client:
                run(client, tokens, ctx)
    except Exception as exc:
        msg = str(exc).splitlines()[0][:200] if str(exc) else ""
        report("-", "unexpected error", False, f"{type(exc).__name__}: {msg}")

    print("\nStep  Result  Check")
    for step, status, name in e2e.results:
        print(f"{step:<5} {status:<7} {name}")
    if ctx:
        print("\nLeft in place (nothing was deleted; list these for the Thursday cleanup):")
        print(f"  document id: {ctx.get('document_id')}")
        print(f"  S3 bucket:   {e2e.settings.s3_bucket}")
        print(f"  S3 key:      {ctx.get('s3_key')}")
    print("ALL PASS" if e2e.failures == 0 else f"{e2e.failures} step(s) FAILED")
    return 1 if e2e.failures else 0


if __name__ == "__main__":
    sys.exit(main())
