"""End-to-end test of the S3 file routes against the REAL Supabase project and REAL S3 bucket.

    cd backend && python ../scripts/e2e_upload.py [--check-expiry] [--base-url http://127.0.0.1:8000]

Signs in as a real user, then drives the API: create a document, get an upload URL, upload a
PDF straight to S3, confirm it, read it back through a download URL, and check tenant
isolation both ways: user B (TEST_USER_B_EMAIL / TEST_USER_B_PASSWORD, a different org) gets
its own document with version 1, and neither user can upload to, confirm on or download from
the other's document. The API runs in-process (TestClient as a context manager, so
the app's lifespan opens the DB pool) unless --base-url points at a running server; the
read-only DB checks need DATABASE_URL either way.

Config comes from .env.local at the repo root (the same file app.config reads):
SUPABASE_URL, SUPABASE_ANON_KEY, TEST_USER_EMAIL, TEST_USER_PASSWORD, TEST_USER_B_EMAIL,
TEST_USER_B_PASSWORD, plus the S3 and
DATABASE_URL settings. Uses only httpx, which the repo already depends on.

Prints PASS/FAIL per step. Never prints tokens, passwords, keys or presigned URLs (only the
host and first path segment). Deletes NOTHING: the test document, its version row and the S3
object stay, and their ids/key are printed at the end so the object can be removed later with
an admin profile. --check-expiry waits ~5 minutes to prove a download link expires.
"""
import argparse
import base64
import hashlib
import json
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import httpx  # noqa: E402
from pydantic_settings import BaseSettings, SettingsConfigDict  # noqa: E402

from app.config import ROOT, settings  # noqa: E402

PDF = "application/pdf"
DOC_TYPE = "nda"
FILENAME = "e2e-upload-test.pdf"


class E2EEnv(BaseSettings):
    """The test-only variables, read from the same .env.local the app uses."""
    model_config = SettingsConfigDict(env_file=ROOT / ".env.local", extra="ignore")

    supabase_anon_key: str = ""
    test_user_email: str = ""
    test_user_password: str = ""
    test_user_b_email: str = ""
    test_user_b_password: str = ""


env = E2EEnv()
results: list[tuple[str, str, str]] = []  # (step, PASS/FAIL/SKIP, name)
failures = 0


def report(step: str, name: str, ok: bool, detail: str = "") -> bool:
    global failures
    failures += 0 if ok else 1
    results.append((step, "PASS" if ok else "FAIL", name))
    print(f"{'PASS' if ok else 'FAIL'}  [{step}] {name}" + (f"  ({detail})" if detail else ""))
    return ok


def skip(step: str, name: str, why: str) -> None:
    results.append((step, "SKIP", name))
    print(f"SKIP  [{step}] {name}  ({why})")


def safe_url(url: str) -> str:
    """Host and first path segment only: a presigned URL's query string is a credential."""
    parts = urlsplit(url)
    first = parts.path.strip("/").split("/")[0]
    return f"{parts.netloc}/{first}" if first else parts.netloc


def api_detail(r: httpx.Response) -> str:
    try:
        return f"HTTP {r.status_code}: {r.json().get('detail')}"
    except Exception:
        return f"HTTP {r.status_code}"


def sample_pdf() -> bytes:
    # A tiny but valid one-page PDF, with a random marker so each run's bytes are unique.
    body = f"BT /F1 12 Tf 20 100 Td (e2e {uuid.uuid4()}) Tj ET".encode()
    return (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
            b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
            b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]/Contents 4 0 R>>endobj\n"
            b"4 0 obj<</Length " + str(len(body)).encode() + b">>stream\n" + body +
            b"\nendstream endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n")


def unverified_claims(token: str) -> dict:
    payload = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))


def password_grant(step: str, name: str, email: str, password: str) -> str | None:
    """Sign in with email/password; returns the access token, or None after reporting a FAIL."""
    try:
        r = httpx.post(f"{settings.supabase_url}/auth/v1/token", params={"grant_type": "password"},
                       headers={"apikey": env.supabase_anon_key},
                       json={"email": email, "password": password}, timeout=30)
    except httpx.HTTPError as exc:
        report(step, name, False, type(exc).__name__)
        return None
    if r.status_code != 200:
        try:
            body = r.json()
        except ValueError:
            body = {}
        report(step, name, False, f"HTTP {r.status_code} {body.get('error_code') or body.get('msg') or ''}".strip())
        return None
    return r.json()["access_token"]


def sign_in() -> str | None:
    required = (("SUPABASE_URL", settings.supabase_url), ("SUPABASE_ANON_KEY", env.supabase_anon_key),
                ("TEST_USER_EMAIL", env.test_user_email), ("TEST_USER_PASSWORD", env.test_user_password))
    missing = [name for name, value in required if not value]
    if not report("1", "test config present", not missing,
                  "missing in .env.local: " + ", ".join(missing) if missing else ""):
        return None
    token = password_grant("1", "sign in", env.test_user_email, env.test_user_password)
    if token is None:
        return None
    report("1", "sign in", True)
    claims = unverified_claims(token)
    role, org = claims.get("user_role"), claims.get("org_id")
    print(f"      user_role: {'present' if role else 'MISSING'} ({role})   "
          f"org_id: {'present' if org else 'MISSING'} ({org})")
    if not role or not org:
        print("FAIL: access token hook is not adding claims")
        report("1", "token has user_role and org_id", False)
        return None
    report("1", "token has user_role and org_id", True)
    return token


def version_numbers(doc_id: str) -> list[int]:
    """The document's version numbers, read over a read-only connection."""
    from app.db import pool

    conn = pool.getconn()
    try:
        conn.read_only = True
        rows = conn.execute("select version_no from document_versions where document_id = %s order by version_no",
                            (doc_id,)).fetchall()
        conn.rollback()
        return [row["version_no"] for row in rows]
    finally:
        conn.read_only = False
        pool.putconn(conn)


def upload_new_document(client, auth: dict, step: str, who: str) -> tuple[str, str] | None:
    """Create an nda document and upload one PDF so it has version 1. Returns (document id, S3 key)."""
    r = client.post("/documents", json={"doc_type": DOC_TYPE}, headers=auth)
    if not report(step, f"{who} creates an '{DOC_TYPE}' document", r.status_code == 201, api_detail(r)):
        return None
    doc_id = r.json()["id"]
    data = sample_pdf()
    r = client.post(f"/documents/{doc_id}/files/upload-url", headers=auth,
                    json={"filename": FILENAME, "content_type": PDF, "size": len(data)})
    if not report(step, f"{who} requests an upload URL", r.status_code == 200, api_detail(r)):
        return None
    post = r.json()
    key = post["key"]
    try:
        up = httpx.post(post["url"], data=post["fields"], files={"file": (FILENAME, data, PDF)}, timeout=60)
    except httpx.HTTPError as exc:
        report(step, f"{who} uploads to S3", False, type(exc).__name__)
        return doc_id, key
    if not report(step, f"{who} uploads to S3", up.status_code in (200, 201, 204), f"HTTP {up.status_code}"):
        return doc_id, key
    r = client.post(f"/documents/{doc_id}/files/confirm", headers=auth, json={"key": key})
    version_no = r.json().get("version_no") if r.status_code == 200 else None
    report(step, f"{who}'s document has version 1", version_no == 1,
           f"version_no {version_no}" if r.status_code == 200 else api_detail(r))
    return doc_id, key


def refused(r: httpx.Response) -> bool:
    """403/404 and no link, upload form or version in the body."""
    try:
        body = r.json()
    except ValueError:
        body = {}
    leaked = isinstance(body, dict) and any(k in body for k in ("url", "fields", "key", "version_no"))
    return r.status_code in (403, 404) and not leaked


def probe_foreign_document(client, auth: dict, doc_id: str, key: str, who: str, owner: str) -> None:
    """`who` tries upload-url, confirm and download-url on a document owned by `owner`."""
    data = sample_pdf()
    before = version_numbers(doc_id)
    attempts = (
        ("upload-url", client.post(f"/documents/{doc_id}/files/upload-url", headers=auth,
                                   json={"filename": FILENAME, "content_type": PDF, "size": len(data)})),
        ("confirm", client.post(f"/documents/{doc_id}/files/confirm", headers=auth, json={"key": key})),
        ("download-url", client.get(f"/documents/{doc_id}/files/download-url", headers=auth,
                                    params={"version_no": 1})),
    )
    for route, r in attempts:
        report("7", f"{who} -> {owner}'s document {route}: 403/404, nothing returned", refused(r),
               f"HTTP {r.status_code}")
    after = version_numbers(doc_id)
    report("7", f"{owner}'s document still has only its original version(s)", after == before,
           f"before {before}, after {after}")


def isolation_check(client, auth_a: dict, org_a: str, doc_a: str, key_a: str, ctx: dict) -> None:
    missing = [n for n, v in (("TEST_USER_B_EMAIL", env.test_user_b_email),
                              ("TEST_USER_B_PASSWORD", env.test_user_b_password)) if not v]
    if missing:
        skip("7", "cross-org isolation", "missing in .env.local: " + ", ".join(missing))
        return
    token_b = password_grant("7", "sign in as user B", env.test_user_b_email, env.test_user_b_password)
    if token_b is None:
        return
    claims_b = unverified_claims(token_b)
    org_b = claims_b.get("org_id")
    if not report("7", "user B is in a different org than user A", bool(org_b) and org_b != org_a,
                  f"B org_id: {org_b}"):
        return
    auth_b = {"Authorization": f"Bearer {token_b}"}
    made = upload_new_document(client, auth_b, "7", "B")
    if made is None:
        return
    doc_b, key_b = made
    ctx.setdefault("extra", []).append((doc_b, key_b))
    if version_numbers(doc_b) != [1]:
        report("7", "B's document has exactly version 1 in the DB", False, f"versions {version_numbers(doc_b)}")
        return
    probe_foreign_document(client, auth_a, doc_b, key_b, "A", "B")
    probe_foreign_document(client, auth_b, doc_a, key_a, "B", "A")


def run(client, token: str, ctx: dict, check_expiry: bool) -> None:
    from app.db import pool

    auth = {"Authorization": f"Bearer {token}"}
    org_id = unverified_claims(token)["org_id"]

    # 2. auth check on a storage route
    probe = f"/documents/{uuid.uuid4()}/files/download-url"
    for label, headers in (("no token", {}), ("garbage token", {"Authorization": "Bearer not.a.token"})):
        r = client.get(probe, headers=headers)
        report("2", f"{label} -> 401", r.status_code == 401, f"HTTP {r.status_code}")

    # 3. create a document. The request schema has no title field (doc_type, state_of_execution,
    # transaction_value only), so the test document is identified by its id and audit trail.
    r = client.post("/documents", json={"doc_type": DOC_TYPE}, headers=auth)
    if not report("3", f"create '{DOC_TYPE}' document", r.status_code == 201, api_detail(r)):
        return
    doc_id = ctx["document_id"] = r.json()["id"]
    print(f"      document id: {doc_id}  (documents has no title column, so 'E2E upload test (safe to delete)' is not stored)")

    # 4. presigned POST, then upload straight to S3
    data = sample_pdf()
    digest = hashlib.sha256(data).hexdigest()
    r = client.post(f"/documents/{doc_id}/files/upload-url", headers=auth,
                    json={"filename": FILENAME, "content_type": PDF, "size": len(data)})
    if not report("4", "request upload URL", r.status_code == 200, api_detail(r)):
        return
    post = r.json()
    key = ctx["s3_key"] = post["key"]
    print(f"      upload target: {safe_url(post['url'])}")
    try:
        # httpx sends the form fields before the file part, which S3 requires.
        up = httpx.post(post["url"], data=post["fields"], files={"file": (FILENAME, data, PDF)}, timeout=60)
    except httpx.HTTPError as exc:
        report("4", "upload PDF to S3", False, type(exc).__name__)
        return
    if not report("4", "upload PDF to S3", up.status_code in (200, 201, 204), f"HTTP {up.status_code}"):
        return

    # 5. confirm, then verify the rows over a read-only connection
    r = client.post(f"/documents/{doc_id}/files/confirm", headers=auth, json={"key": key})
    version_no = r.json().get("version_no") if r.status_code == 200 else None
    if not report("5", "confirm creates version 1", version_no == 1,
                  f"version_no {version_no}" if r.status_code == 200 else api_detail(r)):
        return
    conn = pool.getconn()
    try:
        conn.read_only = True  # the server rejects any write on this connection
        doc = conn.execute("select org_id, doc_type, state from documents where id = %s", (doc_id,)).fetchone()
        report("5", "documents row exists in the user's org", doc is not None and str(doc["org_id"]) == org_id,
               f"doc_type={doc and doc['doc_type']}, state={doc and doc['state']}")
        versions = conn.execute("select version_no, storage_key from document_versions where document_id = %s",
                                (doc_id,)).fetchall()
        report("5", "one document_versions row: version_no 1, right storage_key",
               len(versions) == 1 and versions[0]["version_no"] == 1 and versions[0]["storage_key"] == key,
               f"{len(versions)} row(s)")
        audits = conn.execute("select action, details from audit_logs where document_id = %s order by id",
                              (doc_id,)).fetchall()
        uploaded = [a for a in audits if a["action"] == "file_uploaded"]
        report("5", "audit log row for file_uploaded",
               len(uploaded) == 1 and uploaded[0]["details"].get("storage_key") == key,
               "actions: " + ", ".join(a["action"] for a in audits))
        conn.rollback()
    finally:
        conn.read_only = False
        pool.putconn(conn)

    # 6. download URL, fetch, compare hashes
    link = None
    r = client.get(f"/documents/{doc_id}/files/download-url", params={"version_no": 1}, headers=auth)
    if report("6", "request download URL", r.status_code == 200, api_detail(r)):
        link = r.json()["url"]
        print(f"      download source: {safe_url(link)}   expires_in: {r.json()['expires_in']}s")
        try:
            got = httpx.get(link, timeout=60)
            report("6", "download succeeds", got.status_code == 200, f"HTTP {got.status_code}")
            report("6", "SHA-256 matches the original", hashlib.sha256(got.content).hexdigest() == digest)
        except httpx.HTTPError as exc:
            report("6", "download succeeds", False, type(exc).__name__)

    # 7. tenant isolation, both directions, with a real document owned by user B (another org)
    isolation_check(client, auth, org_id, doc_id, key, ctx)

    # 8. expiry
    if not check_expiry:
        skip("8", "download link expires", "pass --check-expiry")
    elif link is None:
        skip("8", "download link expires", "no link from step 6")
    else:
        wait = max(310, settings.download_url_ttl_seconds + 10)
        print(f"      waiting {wait}s for the link to expire ...")
        time.sleep(wait)
        try:
            late = httpx.get(link, timeout=60)
            report("8", "expired link -> 403", late.status_code == 403, f"HTTP {late.status_code}")
        except httpx.HTTPError as exc:
            report("8", "expired link -> 403", False, type(exc).__name__)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check-expiry", action="store_true")
    ap.add_argument("--base-url", help="use a running server instead of running the app in-process")
    args = ap.parse_args()

    print(f"settings file: {'found' if (ROOT / '.env.local').exists() else 'NOT FOUND'} (.env.local)")
    token = sign_in()
    if token is None:
        return 1
    ctx: dict = {}
    try:
        if args.base_url:
            from app.db import pool
            pool.open()  # the DB checks run here, not in the server
            try:
                with httpx.Client(base_url=args.base_url, timeout=60) as client:
                    run(client, token, ctx, args.check_expiry)
            finally:
                pool.close()
        else:
            from fastapi.testclient import TestClient
            from app.main import app
            with TestClient(app) as client:  # entering the context runs the lifespan (opens the DB pool)
                run(client, token, ctx, args.check_expiry)
    except Exception as exc:
        msg = str(exc).splitlines()[0][:200] if str(exc) else ""
        report("-", "unexpected error", False, f"{type(exc).__name__}: {msg}")

    print("\nStep  Result  Check")
    for step, status, name in results:
        print(f"{step:<5} {status:<7} {name}")
    if ctx:
        print("\nLeft in place (nothing was deleted):")
        print(f"  document id: {ctx.get('document_id')}")
        print(f"  S3 bucket:   {settings.s3_bucket}")
        print(f"  S3 key:      {ctx.get('s3_key')}   (remove it with the admin profile)")
        for extra_doc, extra_key in ctx.get("extra", []):
            print(f"  user B's document id: {extra_doc}")
            print(f"  user B's S3 key:      {extra_key}   (remove it with the admin profile)")
    print("ALL PASS" if failures == 0 else f"{failures} step(s) FAILED")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
