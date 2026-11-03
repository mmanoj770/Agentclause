import json
import uuid
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

from app.agents.conversational import api
from app.agents.conversational.chat_service import ChatService
from app.agents.conversational.classifier import SYSTEM_PROMPT as CLASSIFIER_PROMPT
from app.agents.conversational.embeddings import HashEmbedder
from app.agents.conversational.generation import SYSTEM_PROMPT as GENERATION_PROMPT
from app.agents.conversational.retrieval import DocumentIndex
from app.auth.dependencies import CurrentUser, get_current_user
from app.db import get_conn
from app.main import app

ORG = str(uuid.uuid4())
DOC = str(uuid.uuid4())
LAWYER = str(uuid.uuid4())
QUESTION = "What is the term of this agreement?"
SAMPLE = """1. Term
1.1 The Term of this agreement is five years from the effective date.

2. Governing Law
2.1 This Agreement is governed by the laws of India.
"""
GOOD = json.dumps(
    {"answerable": True, "claims": [{"text": "The term is five years.", "sources": [1]}]}
)
EXPECTED_FIELDS = {
    "turn_id", "document_id", "status", "answer", "citations",
    "reason", "retrieval_score", "escalation_id",
}


class Cursor:
    def __init__(self, row):
        self.row = row

    def fetchone(self):
        return self.row


class RouteConn:
    def __init__(self):
        self.doc = {"id": uuid.UUID(DOC), "org_id": ORG, "assigned_lawyer_id": LAWYER,
                    "state": "lawyer_approved", "doc_type": "nda"}
        self.version = {"id": uuid.uuid4(),
                        "storage_key": f"orgs/{ORG}/documents/{DOC}/abc-nda.txt"}
        self.turns, self.escalations, self.audit = [], [], []
        self.fail_chat_tables = False

    @contextmanager
    def transaction(self):
        yield

    def execute(self, sql, params=()):
        s = " ".join(sql.split())
        if s.startswith("select * from documents where id"):
            return Cursor(self.doc if str(params[0]) == DOC else None)
        if s.startswith("select id, storage_key from document_versions"):
            return Cursor(self.version)
        if s.startswith("insert into chat_") and self.fail_chat_tables:
            raise RuntimeError('relation "chat_turns" does not exist')
        if s.startswith("insert into chat_escalations"):
            self.escalations.append(params)
            return Cursor({"id": uuid.uuid4()})
        if s.startswith("insert into chat_turns"):
            self.turns.append(params)
            return Cursor(None)
        if s.startswith("insert into audit_logs"):
            self.audit.append(params)
            return Cursor(None)
        raise AssertionError(f"unexpected SQL: {s}")


class RouterLLM:
    def complete(self, system: str, user: str, max_tokens: int = 1000) -> str:
        if system == CLASSIFIER_PROMPT:
            return json.dumps({"label": "explain"})
        if system == GENERATION_PROMPT:
            return GOOD
        raise AssertionError("unexpected prompt")


class AlwaysTrue:
    def verify(self, claims, sources):
        return [True] * len(claims)


@pytest.fixture
def env(monkeypatch):
    conn = RouteConn()
    reads = []

    def fake_read(s3, key):
        reads.append(key)
        return SAMPLE.encode()

    monkeypatch.setattr(api, "get_object_bytes", fake_read)
    monkeypatch.setattr(api, "get_s3", lambda: object())
    service = ChatService(None, None, DocumentIndex(HashEmbedder()), RouterLLM(),
                          AlwaysTrue(), threshold=0.3)
    user = CurrentUser(id=str(uuid.uuid4()), email=None, role="startup_user", org_id=ORG)
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_conn] = lambda: conn
    app.dependency_overrides[api.get_chat_service] = lambda: service
    yield type("Env", (), {"client": TestClient(app), "conn": conn, "reads": reads})
    app.dependency_overrides.clear()


def post(env, question, **extra):
    return env.client.post(f"/documents/{DOC}/chat", json={"question": question, **extra})


def test_answer_has_the_contract_shape_and_is_logged_without_the_question(env):
    r = post(env, QUESTION)
    assert r.status_code == 200
    body = r.json()
    assert set(body) == EXPECTED_FIELDS
    assert body["status"] == "answered"
    assert body["answer"] == "The term is five years."
    assert body["citations"][0]["clause_number"] == "1.1"
    assert len(env.conn.turns) == 1
    assert env.conn.audit[0][3] == "chat_turn"
    details = env.conn.audit[0][4].obj
    assert QUESTION not in str(details)
    assert details["question_length"] == len(QUESTION)


def test_closed_state_is_refused_and_no_file_is_read(env):
    env.conn.doc["state"] = "pending_lawyer_review"
    body = post(env, QUESTION).json()
    assert body["status"] == "refused" and body["reason"] == "document_not_ready"
    assert env.reads == []


def test_image_upload_is_refused_as_unreadable(env):
    env.conn.version["storage_key"] = f"orgs/{ORG}/documents/{DOC}/abc-scan.png"
    body = post(env, QUESTION).json()
    assert body["reason"] == "document_unreadable"
    assert "Scanned or image uploads" in body["answer"]
    assert env.reads == []


def test_advice_question_is_escalated_and_saved(env):
    body = post(env, "Should I sue them?").json()
    assert body["status"] == "escalated" and body["escalation_id"]
    assert len(env.conn.escalations) == 1


@pytest.mark.parametrize("payload", [
    {"question": ""},
    {"question": "   "},
    {"question": "a" * 1001},
    {"question": "term?", "language": "hi"},
])
def test_bad_input_is_422(env, payload):
    assert env.client.post(f"/documents/{DOC}/chat", json=payload).status_code == 422


def test_missing_chat_tables_do_not_break_answers_or_escalations(env):
    env.conn.fail_chat_tables = True
    answered = post(env, QUESTION)
    assert answered.status_code == 200 and answered.json()["status"] == "answered"
    escalated = post(env, "Should I sue them?")
    assert escalated.status_code == 200
    body = escalated.json()
    assert body["status"] == "escalated" and body["escalation_id"] is None
    assert "contact your advocate directly" in body["answer"]
