"""Read-only check that a lawyer account can sign in and use the API on the live project.

    cd backend && LAWYER_EMAIL=... LAWYER_PASSWORD=... python ../scripts/check_lawyer_login.py [--base-url URL]

Signs in the way scripts/e2e_upload.py does (Supabase password grant, anon key from .env.local or the
environment), then reports:
  1. whether the token carries user_role and org_id (claim names and values only; for a lawyer the
     org_id claim should be absent or null),
  2. GET /me: status and the role/org the profile returns,
  3. GET /queue: status,
  4. GET /documents: status.
It only reads: three GETs and one sign-in. It creates and deletes nothing, writes no files, and never
prints the email, the password, the token, a user id or an org id (an org is reported as absent/null/set).
The API runs in-process (TestClient) unless --base-url points at a running server; the app needs the
usual .env.local settings (DATABASE_URL, SUPABASE_URL, ...).
"""
import argparse
import base64
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import httpx  # noqa: E402
from pydantic_settings import BaseSettings, SettingsConfigDict  # noqa: E402

failures = 0


def report(name: str, ok: bool, detail: str = "") -> bool:
    global failures
    if not ok:
        failures += 1
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""))
    return ok


def org_state(value, present: bool = True) -> str:
    if not present:
        return "absent"
    return "null" if value is None else "set"


def unverified_claims(token: str) -> dict:
    payload = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", help="use a running server instead of running the app in-process")
    args = ap.parse_args()

    email, password = os.environ.get("LAWYER_EMAIL", ""), os.environ.get("LAWYER_PASSWORD", "")
    missing = [n for n, v in (("LAWYER_EMAIL", email), ("LAWYER_PASSWORD", password)) if not v]
    if missing:
        print("FAIL  missing environment variables: " + ", ".join(missing))
        return 2

    from app.config import ROOT, settings  # imported late so a missing variable fails fast, with no DB

    class Env(BaseSettings):
        model_config = SettingsConfigDict(env_file=ROOT / ".env.local", extra="ignore")
        supabase_anon_key: str = ""

    anon_key = Env().supabase_anon_key
    if not (settings.supabase_url and anon_key):
        print("FAIL  SUPABASE_URL or SUPABASE_ANON_KEY is not configured")
        return 2

    try:
        r = httpx.post(f"{settings.supabase_url}/auth/v1/token", params={"grant_type": "password"},
                       headers={"apikey": anon_key}, json={"email": email, "password": password}, timeout=30)
    except httpx.HTTPError as exc:
        report("sign in", False, type(exc).__name__)
        return 1
    if r.status_code != 200:
        try:
            body = r.json()
        except ValueError:
            body = {}
        report("sign in", False, f"HTTP {r.status_code} {body.get('error_code') or body.get('msg') or ''}".strip())
        return 1
    token = r.json()["access_token"]
    report("sign in", True)

    # 1. claims
    claims = unverified_claims(token)
    role = claims.get("user_role")
    has_org_claim = "org_id" in claims
    org = org_state(claims.get("org_id"), has_org_claim)
    report("token has a user_role claim", role is not None, f"user_role = {role}")
    print(f"      org_id claim: {org}")
    report("user_role is 'lawyer'", role == "lawyer")
    report("org_id claim is absent or null (lawyers have no org)", org in ("absent", "null"), f"org_id {org}")

    auth = {"Authorization": f"Bearer {token}"}

    def run(client) -> None:
        # 2. /me
        r = client.get("/me", headers=auth)
        profile = (r.json() or {}).get("profile") if r.status_code == 200 else None
        report("GET /me", r.status_code == 200, f"HTTP {r.status_code}")
        if profile:
            print(f"      profile role: {profile.get('role')}   profile org_id: {org_state(profile.get('org_id'))}")
            report("profile role is 'lawyer' and org_id is null",
                   profile.get("role") == "lawyer" and profile.get("org_id") is None)
        elif r.status_code == 200:
            report("profile row exists", False, "profile is null")
        # 3. /queue
        r = client.get("/queue", headers=auth)
        n = len(r.json()) if r.status_code == 200 and isinstance(r.json(), list) else None
        report("GET /queue", r.status_code == 200, f"HTTP {r.status_code}" + (f", {n} item(s)" if n is not None else ""))
        # 4. /documents
        r = client.get("/documents", headers=auth)
        n = len(r.json()) if r.status_code == 200 and isinstance(r.json(), list) else None
        report("GET /documents", r.status_code == 200, f"HTTP {r.status_code}" + (f", {n} document(s)" if n is not None else ""))

    try:
        if args.base_url:
            with httpx.Client(base_url=args.base_url, timeout=60) as client:
                run(client)
        else:
            from fastapi.testclient import TestClient
            from app.main import app
            with TestClient(app) as client:  # entering the context runs the lifespan (opens the DB pool)
                run(client)
    except Exception as exc:
        msg = str(exc).splitlines()[0][:200] if str(exc) else ""
        report("unexpected error", False, f"{type(exc).__name__}: {msg}")

    print("ALL PASS" if failures == 0 else f"{failures} check(s) FAILED")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
