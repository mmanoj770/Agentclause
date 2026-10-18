"""Startup findings route: GET /documents/{id}/client-findings. No database: the connection is a fake."""
import uuid

import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import CurrentUser, get_current_user
from app.db import get_conn
from app.main import app

ORG_A, ORG_B = str(uuid.uuid4()), str(uuid.uuid4())
DOC = str(uuid.uuid4())
LAWYER = str(uuid.uuid4())
URL = f"/documents/{DOC}/client-findings"
ALLOWED_KEYS = {"finding_id", "severity", "clause_reference", "description", "remedy_suggested",
                "citation", "citation_type", "status", "origin"}


def row(action, severity="high", **extra):
    base = {"id": uuid.uuid4(), "severity": severity, "clause_reference": "Clause 3.1",
            "description": f"issue ({action})", "remedy_suggested": "fix it",
            "citation": "Indian Contract Act, 1872, s. 27", "citation_type": "STATUTORY",
            "advocate_action": action}
    base.update(extra)
    return base


class Result:
    def __init__(self, rows):
        self.rows = rows

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


class FakeConn:
    def __init__(self, state="lawyer_approved", rows=None):
        self.doc = {"id": uuid.UUID(DOC), "org_id": ORG_A, "assigned_lawyer_id": LAWYER, "state": state}
        self.rows = rows if rows is not None else []
        self.sql = []

    def execute(self, sql, params=()):
        s = " ".join(sql.split())
        self.sql.append(s)
        if s.startswith("select * from documents where id"):
            return Result([self.doc] if str(params[0]) == DOC else [])
        if s.startswith("select f.id, f.severity"):
            return Result(self.rows)
        raise AssertionError(f"unexpected SQL: {s}")


@pytest.fixture
def env():
    conn = FakeConn()
    state = {"user": CurrentUser(id=str(uuid.uuid4()), email=None, role="startup_user", org_id=ORG_A)}
    app.dependency_overrides[get_current_user] = lambda: state["user"]
    app.dependency_overrides[get_conn] = lambda: conn
    yield type("Env", (), {"client": TestClient(app), "conn": conn, "state": state})
    app.dependency_overrides.clear()


def test_returns_confirmed_and_lawyer_added_findings_with_origin(env):
    env.conn.rows = [row("confirm", "critical"), row("add", "low")]
    r = env.client.get(URL)
    assert r.status_code == 200
    body = r.json()
    assert [(f["status"], f["origin"]) for f in body] == [("confirmed", "agent"), ("added", "advocate")]
    assert all(set(f) == ALLOWED_KEYS for f in body)


def test_works_for_delivered_documents(env):
    env.conn.doc["state"] = "delivered"
    env.conn.rows = [row("confirm")]
    assert env.client.get(URL).status_code == 200


def test_internal_fields_never_reach_the_client(env):
    """Planted: the row carries layer, rule_applied and lawyer notes. None of it may appear."""
    env.conn.rows = [row("confirm", layer=2, rule_applied="SECRET_RULE_ID",
                         advocate_notes="lawyer private note", adjudicated_by=LAWYER)]
    r = env.client.get(URL)
    text = r.text
    for leaked in ("SECRET_RULE_ID", "lawyer private note", LAWYER, "rule_applied", "layer",
                   "advocate_notes", "adjudicated_by"):
        assert leaked not in text
    assert set(r.json()[0]) == ALLOWED_KEYS


def test_pending_and_overridden_findings_are_dropped_even_if_the_query_returns_them(env):
    env.conn.rows = [row(None), row("override"), row("confirm")]
    r = env.client.get(URL)
    assert [f["status"] for f in r.json()] == ["confirmed"]


def test_query_selects_only_the_allowed_columns_and_filters_to_the_latest_version(env):
    env.conn.rows = [row("confirm")]
    env.client.get(URL)
    q = next(s for s in env.conn.sql if s.startswith("select f.id"))
    assert "advocate_action in ('confirm', 'add')" in q
    assert "max(version_no)" in q
    for column in ("rule_applied", "advocate_notes", "f.layer", "f.*"):
        assert column not in q


@pytest.mark.parametrize("state", ["drafted", "under_ai_review", "pending_lawyer_review",
                                    "lawyer_commented", "revision_in_progress"])
def test_not_available_before_sign_off(env, state):
    env.conn.doc["state"] = state
    env.conn.rows = [row("confirm")]
    assert env.client.get(URL).status_code == 409


def test_document_lookup_comes_first_so_other_orgs_get_404_not_a_state_hint(env):
    env.conn.doc["state"] = "drafted"
    env.state["user"] = CurrentUser(id="x", email=None, role="startup_user", org_id=ORG_B)
    assert env.client.get(URL).status_code == 404
    assert not any(s.startswith("select f.id") for s in env.conn.sql)


@pytest.mark.parametrize("org_id", [None, ""])
def test_account_without_an_organisation_sees_nothing(env, org_id):
    env.state["user"] = CurrentUser(id="x", email=None, role="startup_user", org_id=org_id)
    assert env.client.get(URL).status_code == 404


def test_unknown_document_is_404(env):
    assert env.client.get(f"/documents/{uuid.uuid4()}/client-findings").status_code == 404


def test_lawyers_use_the_lawyer_route_not_this_one(env):
    env.state["user"] = CurrentUser(id=LAWYER, email=None, role="lawyer", org_id=None)
    assert env.client.get(URL).status_code == 403


def test_no_token_is_401():
    app.dependency_overrides.clear()
    assert TestClient(app).get(URL).status_code in (401, 403)
