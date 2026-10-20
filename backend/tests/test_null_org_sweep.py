"""Route sweep: every route, called by every kind of caller who must NOT get in.

No database and no live login. The token decoder is replaced, so the real claim parsing and the
real dependencies run. The fake connection answers ONLY the document lookup (and the finding row
for adjudicate); a denied caller that gets past that point fails the test, as does any org-scoped
query run with a null or empty org. A control group proves the fake data is reachable, so the
sweep cannot pass by finding nothing.
"""
import uuid

import pytest
from fastapi.testclient import TestClient

from app.auth import dependencies
from app.db import get_conn
from app.main import app
from app.storage import s3 as storage

ORG_A, ORG_B = str(uuid.uuid4()), str(uuid.uuid4())
OWNER, LAWYER, OTHER_LAWYER = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
DOC, FID = str(uuid.uuid4()), str(uuid.uuid4())
MARKER = "SECRET-DOC-DESCRIPTION"

CLAIMS = {
    "startup_org_a": {"sub": OWNER, "user_role": "startup_user", "org_id": ORG_A},
    "assigned_lawyer": {"sub": LAWYER, "user_role": "lawyer"},
    "startup_no_org_claim": {"sub": str(uuid.uuid4()), "user_role": "startup_user"},
    "startup_org_null": {"sub": str(uuid.uuid4()), "user_role": "startup_user", "org_id": None},
    "startup_org_empty": {"sub": str(uuid.uuid4()), "user_role": "startup_user", "org_id": ""},
    "startup_org_b": {"sub": str(uuid.uuid4()), "user_role": "startup_user", "org_id": ORG_B},
    "unassigned_lawyer": {"sub": OTHER_LAWYER, "user_role": "lawyer"},
    "no_role": {"sub": str(uuid.uuid4()), "org_id": ORG_A},
}
STARTUP_DENIED = ["startup_no_org_claim", "startup_org_null", "startup_org_empty", "startup_org_b"]
LAWYER_DENIED = ["unassigned_lawyer"]


class Result:
    def __init__(self, rows):
        self.rows = rows

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


class StrictConn:
    def __init__(self):
        self.doc = {"id": uuid.UUID(DOC), "org_id": ORG_A, "assigned_lawyer_id": LAWYER,
                    "state": "pending_lawyer_review", "doc_type": "nda", "note": MARKER}
        self.finding = {"id": uuid.UUID(FID), "document_id": uuid.UUID(DOC), "layer": 2,
                        "advocate_action": None, "doc_state": "pending_lawyer_review",
                        "assigned_lawyer_id": LAWYER, "description": MARKER}
        self.seen = []

    def transaction(self):
        class Tx:
            def __enter__(s): return s
            def __exit__(s, *a): return False
        return Tx()

    def execute(self, sql, params=()):
        s = " ".join(sql.split())
        self.seen.append(s)
        if "org_id" in s and any(p is None or p == "" for p in params):
            raise AssertionError(f"org-scoped query ran with a null or empty org: {s} {params}")
        if s.startswith("select * from documents where id"):
            return Result([self.doc] if str(params[0]) == DOC else [])
        if s.startswith("select f.*, d.state as doc_state"):
            return Result([self.finding] if str(params[0]) == FID else [])
        if s.startswith("select * from documents where org_id"):
            return Result([self.doc] if params[0] == ORG_A else [])
        if s.startswith("select * from documents where assigned_lawyer_id"):
            return Result([self.doc] if params[0] == LAWYER else [])
        raise AssertionError(f"a caller who should have been refused reached: {s}")


class NoS3:
    def __getattr__(self, name):
        raise AssertionError(f"a refused caller reached S3 ({name})")


@pytest.fixture
def api(monkeypatch):
    conn = StrictConn()
    monkeypatch.setattr(dependencies, "_decode", lambda token: CLAIMS[token])
    app.dependency_overrides[get_conn] = lambda: conn
    app.dependency_overrides[storage.get_s3] = lambda: NoS3()
    client = TestClient(app)

    def call(method, path, who=None, body=None):
        headers = {"Authorization": f"Bearer {who}"} if who else {}
        return client.request(method, path, json=body if body is not None else {}, headers=headers)

    yield type("Api", (), {"call": staticmethod(call), "conn": conn})
    app.dependency_overrides.clear()


DRAFT = {"disclosing_party": "A", "receiving_party": "B", "effective_date": "2026-10-21", "term_months": 12}
# (method, path, body, who may call it)
DOC_ROUTES = [
    ("GET", f"/documents/{DOC}", None, "any"),
    ("POST", f"/documents/{DOC}/transition", {"to_state": "under_ai_review"}, "any"),
    ("GET", f"/documents/{DOC}/files/download-url", None, "any"),
    ("POST", f"/documents/{DOC}/files/upload-url",
     {"filename": "a.pdf", "content_type": "application/pdf", "size": 100}, "startup"),
    ("POST", f"/documents/{DOC}/files/confirm", {"key": "x"}, "startup"),
    ("POST", f"/documents/{DOC}/review", None, "startup"),
    ("POST", f"/documents/{DOC}/chat", {"question": "what does clause 3 mean?"}, "any"),
    ("POST", f"/documents/{DOC}/draft", DRAFT, "startup"),
    ("GET", f"/documents/{DOC}/client-findings", None, "startup"),
    ("GET", f"/documents/{DOC}/findings", None, "lawyer"),
    ("POST", f"/documents/{DOC}/findings", {"severity": "low", "description": "x"}, "lawyer"),
    ("POST", f"/findings/{FID}/adjudicate", {"action": "confirm"}, "lawyer"),
]
QUEUE_ROUTES = [
    ("GET", "/queue", None), ("POST", f"/queue/{DOC}/claim", None),
    ("POST", f"/queue/{DOC}/release", None), ("POST", f"/queue/{DOC}/declare-conflict", {}),
]


def expected(needs, who):
    role = CLAIMS[who]["user_role"]
    if needs == "any" or needs == ("startup" if role == "startup_user" else "lawyer"):
        return 404          # right role, but not their document
    return 403             # wrong role for the route


def ids():
    return lambda v: v if isinstance(v, str) and not v.startswith("/") else None


@pytest.mark.parametrize("method,path,body,needs", DOC_ROUTES, ids=[f"{m} {p[:48]}" for m, p, _, _ in DOC_ROUTES])
@pytest.mark.parametrize("who", STARTUP_DENIED + LAWYER_DENIED)
def test_callers_outside_the_document_are_refused(api, who, method, path, body, needs):
    r = api.call(method, path, who, body)
    assert r.status_code == expected(needs, who), (who, method, path, r.status_code, r.text)
    assert MARKER not in r.text and DOC not in r.text.replace(path, "")
    assert not any(q.startswith(("insert", "update", "delete")) for q in api.conn.seen)


@pytest.mark.parametrize("method,path,body", QUEUE_ROUTES, ids=[f"{m} {p[:40]}" for m, p, _ in QUEUE_ROUTES])
@pytest.mark.parametrize("who", STARTUP_DENIED)
def test_startup_users_never_reach_the_lawyer_queue(api, who, method, path, body):
    assert api.call(method, path, who, body).status_code == 403
    assert api.conn.seen == []


@pytest.mark.parametrize("who", STARTUP_DENIED + LAWYER_DENIED)
def test_listing_documents_returns_nothing_to_outsiders(api, who):
    r = api.call("GET", "/documents", who)
    assert r.status_code == 200 and r.json() == []
    assert MARKER not in r.text


@pytest.mark.parametrize("who", ["startup_no_org_claim", "startup_org_null", "startup_org_empty"])
def test_a_startup_user_without_an_org_cannot_create_a_document(api, who):
    r = api.call("POST", "/documents", who, {"doc_type": "nda"})
    assert r.status_code == 400
    assert api.conn.seen == []


def test_a_lawyer_cannot_create_a_document(api):
    assert api.call("POST", "/documents", "unassigned_lawyer", {"doc_type": "nda"}).status_code == 403


ALL_ROUTES = [(m, p, b) for m, p, b, _ in DOC_ROUTES] + QUEUE_ROUTES + [("GET", "/documents", None)]


@pytest.mark.parametrize("method,path,body", ALL_ROUTES, ids=[f"{m} {p[:48]}" for m, p, _ in ALL_ROUTES])
def test_no_token_is_401(api, method, path, body):
    assert api.call(method, path, None, body).status_code == 401
    assert api.conn.seen == []


@pytest.mark.parametrize("method,path,body", ALL_ROUTES, ids=[f"{m} {p[:48]}" for m, p, _ in ALL_ROUTES])
def test_a_token_with_no_role_is_403(api, method, path, body):
    assert api.call(method, path, "no_role", body).status_code == 403
    assert api.conn.seen == []


# --- controls: the fake data is reachable, so the refusals above mean something ---------------------

def test_control_the_owning_startup_user_sees_the_document(api):
    r = api.call("GET", f"/documents/{DOC}", "startup_org_a")
    assert r.status_code == 200 and r.json()["note"] == MARKER
    assert api.call("GET", "/documents", "startup_org_a").json()[0]["note"] == MARKER


def test_control_the_assigned_lawyer_sees_the_document(api):
    r = api.call("GET", f"/documents/{DOC}", "assigned_lawyer")
    assert r.status_code == 200 and r.json()["note"] == MARKER


def test_control_the_strict_connection_really_does_fail_on_a_null_org(api):
    with pytest.raises(AssertionError, match="null or empty org"):
        api.conn.execute("select * from documents where org_id = %s", (None,))
