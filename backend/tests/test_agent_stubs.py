"""X1 stub agent routes, with no database: the DB connection is an in-memory fake."""
import uuid

import pytest
from fastapi.testclient import TestClient

from app.agents import fixtures, service
from app.auth.dependencies import CurrentUser, get_current_user
from app.db import get_conn
from app.main import app
from app.schemas.finding import INSERT_COLUMNS, Finding

ORG_A, ORG_B = str(uuid.uuid4()), str(uuid.uuid4())
DOC = str(uuid.uuid4())
LAWYER = str(uuid.uuid4())


class Result:
    def __init__(self, rows):
        self.rows = rows

    def fetchone(self):
        return self.rows[0] if self.rows else None


class FakeConn:
    def __init__(self, state="drafted", with_version=True):
        self.doc = {"id": uuid.UUID(DOC), "org_id": ORG_A, "assigned_lawyer_id": LAWYER,
                    "state": state, "doc_type": "nda"}
        self.version = {"id": uuid.uuid4(), "version_no": 1} if with_version else None
        self.findings, self.audit, self.moves = [], [], []

    def transaction(self):
        class Tx:
            def __enter__(s): return s
            def __exit__(s, *a): return False
        return Tx()

    def execute(self, sql, params=()):
        s = " ".join(sql.split())
        if s.startswith("select * from documents where id"):
            return Result([self.doc] if str(params[0]) == DOC else [])
        if s.startswith("select id, version_no from document_versions"):
            return Result([self.version] if self.version else [])
        if s.startswith("select 1 from findings where document_version_id"):
            return Result([{"?column?": 1}] if any(f["document_version_id"] == params[0]
                                                    for f in self.findings) else [])
        if s.startswith("insert into findings"):
            self.findings.append(dict(zip(INSERT_COLUMNS, params)))
            return Result([])
        if s.startswith("insert into audit_logs"):
            self.audit.append(params)
            return Result([])
        raise AssertionError(f"unexpected SQL: {s}")


@pytest.fixture
def env(monkeypatch):
    conn = FakeConn()

    def fake_transition(c, doc_id, to_state, actor, note=None):
        assert actor.kind == "system"
        conn.moves.append(to_state.value)
        conn.doc["state"] = to_state.value
        return conn.doc

    monkeypatch.setattr(service, "transition", fake_transition)
    state = {"user": CurrentUser(id=str(uuid.uuid4()), email=None, role="startup_user", org_id=ORG_A)}
    app.dependency_overrides[get_current_user] = lambda: state["user"]
    app.dependency_overrides[get_conn] = lambda: conn
    yield type("Env", (), {"client": TestClient(app), "conn": conn, "state": state})
    app.dependency_overrides.clear()


def test_fixture_findings_are_valid_r1_findings():
    findings = fixtures.sample_findings()
    assert len(findings) >= 3
    assert all(isinstance(f, Finding) for f in findings)
    assert all(f.description.startswith(fixtures.STUB_TAG) for f in findings)
    assert len({f.finding_id for f in findings}) == len(findings)


def test_review_moves_document_to_lawyer_queue_and_stores_findings(env):
    r = env.client.post(f"/documents/{DOC}/review")
    assert r.status_code == 200
    assert r.json() == {"state": "pending_lawyer_review", "version_no": 1,
                        "findings_created": len(fixtures.sample_findings())}
    assert env.conn.moves == ["under_ai_review", "pending_lawyer_review"]
    assert len(env.conn.findings) == r.json()["findings_created"]
    assert all(f["document_version_id"] == env.conn.version["id"] for f in env.conn.findings)
    assert all(f["advocate_action"] is None and f["citation"] and f["citation_type"]
               for f in env.conn.findings)


def test_review_needs_an_uploaded_version(env):
    env.conn.version = None
    assert env.client.post(f"/documents/{DOC}/review").status_code == 409
    assert env.conn.moves == []


def test_review_refused_outside_reviewable_states(env):
    env.conn.doc["state"] = "pending_lawyer_review"
    assert env.client.post(f"/documents/{DOC}/review").status_code == 409


def test_review_hidden_from_other_org_and_closed_to_lawyers(env):
    env.state["user"] = CurrentUser(id="x", email=None, role="startup_user", org_id=ORG_B)
    assert env.client.post(f"/documents/{DOC}/review").status_code == 404
    env.state["user"] = CurrentUser(id=LAWYER, email=None, role="lawyer", org_id=None)
    assert env.client.post(f"/documents/{DOC}/review").status_code == 403


@pytest.mark.parametrize("question,status", [
    ("Who has to keep the information confidential?", "answered"),
    ("How long does the agreement last?", "answered"),
    ("Should I sign this agreement?", "escalated"),
    ("Can I sue them under this contract?", "escalated"),
    ("What is the capital of France?", "refused"),
])
def test_chat_covers_answered_refused_escalated(env, question, status):
    r = env.client.post(f"/documents/{DOC}/chat", json={"question": question})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == status
    assert body["language"] == "en"
    if status == "answered":
        assert body["answer"] and body["citations"] and body["reason"] is None
    else:  # C1: refused and escalated carry a reason, no answer, no citations
        assert body["answer"] is None and body["citations"] == [] and body["reason"]
    assert len(env.conn.audit) == 1  # every turn is logged
    action, details = env.conn.audit[0][3], env.conn.audit[0][4].obj
    assert action == "chat_turn"
    assert details == {"question_length": len(question), "status": status, "stub": True}
    assert question not in str(details)  # the raw question is not stored


def test_chat_visible_to_assigned_lawyer_only(env):
    env.state["user"] = CurrentUser(id=LAWYER, email=None, role="lawyer", org_id=None)
    assert env.client.post(f"/documents/{DOC}/chat", json={"question": "What is the term?"}).status_code == 200
    env.state["user"] = CurrentUser(id=str(uuid.uuid4()), email=None, role="lawyer", org_id=None)
    assert env.client.post(f"/documents/{DOC}/chat", json={"question": "What is the term?"}).status_code == 404


def test_chat_rejects_empty_question_and_other_languages(env):
    assert env.client.post(f"/documents/{DOC}/chat", json={"question": ""}).status_code == 422
    assert env.client.post(f"/documents/{DOC}/chat",
                           json={"question": "term?", "language": "hi"}).status_code == 422


def test_draft_returns_labelled_staging_clauses(env):
    body = {"disclosing_party": "Acme Pvt Ltd", "receiving_party": "Beta LLP",
            "effective_date": "2026-11-01", "term_months": 24}
    r = env.client.post(f"/documents/{DOC}/draft", json=body)
    assert r.status_code == 200
    out = r.json()
    assert out["source_tier"] == "staging" and "not lawyer-verified" in out["draft_label"]
    assert all(c["source_tier"] == "staging" for c in out["clauses"])
    assert "Acme Pvt Ltd" in out["clauses"][0]["text"]
    assert [a[3] for a in env.conn.audit] == ["draft_generated"]


DRAFT_BODY = {"disclosing_party": "Acme Pvt Ltd", "receiving_party": "Beta LLP",
              "effective_date": "2026-11-01", "term_months": 24}
CHAT_BODY = {"question": "How long does the agreement last?"}
ROUTES = [("review", None), ("chat", CHAT_BODY), ("draft", DRAFT_BODY)]


@pytest.fixture
def anon(monkeypatch):
    """No auth override: the real get_current_user runs. Only the DB is faked."""
    conn = FakeConn()
    app.dependency_overrides[get_conn] = lambda: conn
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.mark.parametrize("route,body", ROUTES)
@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer not.a.token"}],
                         ids=["no-token", "invalid-token"])
def test_routes_need_a_valid_token(anon, route, body, headers):
    assert anon.post(f"/documents/{DOC}/{route}", json=body, headers=headers).status_code == 401


@pytest.mark.parametrize("route,body", ROUTES)
def test_unknown_document_is_404(env, route, body):
    assert env.client.post(f"/documents/{uuid.uuid4()}/{route}", json=body).status_code == 404
    assert env.conn.findings == [] and env.conn.audit == []


def test_draft_refused_outside_reviewable_states(env):
    env.conn.doc["state"] = "pending_lawyer_review"
    assert env.client.post(f"/documents/{DOC}/draft", json=DRAFT_BODY).status_code == 409
    assert env.conn.audit == []


@pytest.mark.parametrize("route,body", [("draft", DRAFT_BODY), ("chat", CHAT_BODY)])
def test_other_org_gets_404(env, route, body):
    env.state["user"] = CurrentUser(id="x", email=None, role="startup_user", org_id=ORG_B)
    assert env.client.post(f"/documents/{DOC}/{route}", json=body).status_code == 404
    assert env.conn.audit == []


def test_lawyer_cannot_draft(env):
    env.state["user"] = CurrentUser(id=LAWYER, email=None, role="lawyer", org_id=None)
    assert env.client.post(f"/documents/{DOC}/draft", json=DRAFT_BODY).status_code == 403
    assert env.conn.audit == []


def test_second_review_of_the_same_version_is_409_and_adds_nothing(env):
    assert env.client.post(f"/documents/{DOC}/review").status_code == 200
    stored, moves = len(env.conn.findings), list(env.conn.moves)
    env.conn.doc["state"] = "revision_in_progress"  # reviewable again, but no revised version uploaded
    r = env.client.post(f"/documents/{DOC}/review")
    assert r.status_code == 409 and "already been reviewed" in r.json()["detail"]
    assert len(env.conn.findings) == stored and env.conn.moves == moves


def test_review_allowed_again_on_a_new_version(env):
    assert env.client.post(f"/documents/{DOC}/review").status_code == 200
    env.conn.doc["state"] = "revision_in_progress"
    env.conn.version = {"id": uuid.uuid4(), "version_no": 2}
    r = env.client.post(f"/documents/{DOC}/review")
    assert r.status_code == 200 and r.json()["version_no"] == 2


@pytest.mark.parametrize("route,body", [("review", None), ("draft", DRAFT_BODY)])
def test_other_doc_types_are_422_until_they_have_an_agent(env, route, body):
    env.conn.doc["doc_type"] = "employment_agreement"
    r = env.client.post(f"/documents/{DOC}/{route}", json=body)
    assert r.status_code == 422 and "only available for NDAs" in r.json()["detail"]
    assert env.conn.findings == [] and env.conn.moves == [] and env.conn.audit == []
