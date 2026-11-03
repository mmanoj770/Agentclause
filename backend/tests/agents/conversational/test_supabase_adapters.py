from contextlib import contextmanager
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from psycopg.types.json import Jsonb

from app.agents.conversational.chat_service import ChatUser, TurnRecord
from app.agents.conversational.supabase_adapters import (
    SupabaseChatLog,
    SupabaseDocumentSource,
)

DOC = uuid4()
USER = ChatUser(id=str(uuid4()), role="startup_user")


class FakeCursor:
    def __init__(self, row):
        self.row = row

    def fetchone(self):
        return self.row


class FakeConn:
    def __init__(self, version_row=None):
        self.version_row = version_row
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        if "document_versions" in sql:
            return FakeCursor(self.version_row)
        if "chat_escalations" in sql:
            return FakeCursor({"id": uuid4()})
        return FakeCursor(None)

    @contextmanager
    def transaction(self):
        yield


def make_source(conn, document=None):
    reads = []

    def read_object(s3, key):
        reads.append((s3, key))
        return b"file"

    document = document if document is not None else {"state": "lawyer_approved"}
    source = SupabaseDocumentSource(
        conn, "original-user", lambda c, d, u: document, read_object, lambda: "s3-client"
    )
    return source, reads


def record(version="v-1"):
    return TurnRecord(
        turn_id=uuid4(),
        document_id=DOC,
        document_version_id=version,
        asked_by=USER.id,
        question="q",
        answer="a",
        status="answered",
        reason=None,
        stage="answered",
        classifier_source="llm",
        attempts=1,
        retrieval_score=0.5,
        citations=[{"chunk_id": "c1"}],
        escalation_id=None,
        latency_ms=12,
    )


def test_load_document_returns_state_key_and_version():
    version_id = uuid4()
    source, _ = make_source(FakeConn({"id": version_id, "storage_key": "org/doc/abc-nda.pdf"}))
    info = source.load_document(DOC, USER)
    assert info.state == "lawyer_approved"
    assert info.storage_key == "org/doc/abc-nda.pdf"
    assert info.version_id == str(version_id)
    assert info.filename == "abc-nda.pdf"


def test_read_file_only_for_key_issued_by_load_document_and_uses_s3_factory():
    source, reads = make_source(FakeConn({"id": uuid4(), "storage_key": "org/doc/abc-nda.pdf"}))
    info = source.load_document(DOC, USER)
    assert source.read_file(info.storage_key) == b"file"
    with pytest.raises(PermissionError):
        source.read_file("org/other/secret.pdf")
    assert reads == [("s3-client", "org/doc/abc-nda.pdf")]


def test_document_without_version_cannot_be_read():
    source, reads = make_source(FakeConn(None))
    info = source.load_document(DOC, USER)
    assert info.storage_key == "" and info.version_id == "none"
    with pytest.raises(PermissionError):
        source.read_file("")
    assert reads == []


def test_state_accepts_enum_like_and_object_documents():
    class State:
        value = "lawyer_approved"

    source, _ = make_source(FakeConn(None), document=SimpleNamespace(state=State()))
    assert source.load_document(DOC, USER).state == "lawyer_approved"


def test_access_errors_propagate_and_original_user_is_passed():
    seen = {}

    def deny(conn, doc, user):
        seen["user"] = user
        raise PermissionError("404")

    source = SupabaseDocumentSource(
        FakeConn(None), "original-user", deny, lambda s, k: b"", lambda: "s3"
    )
    with pytest.raises(PermissionError):
        source.load_document(DOC, USER)
    assert seen["user"] == "original-user"


def test_save_turn_uses_jsonb_citations_and_null_for_missing_version():
    conn = FakeConn()
    SupabaseChatLog(conn, lambda *a, **k: None).save_turn(record(version="none"))
    sql, params = conn.executed[0]
    assert "chat_turns" in sql
    assert params[2] is None
    assert isinstance(params[12], Jsonb)


def test_save_escalation_returns_uuid_and_passes_params():
    conn = FakeConn()
    escalation_id = SupabaseChatLog(conn, lambda *a, **k: None).save_escalation(
        DOC, "Should I sue them?", USER.id
    )
    assert isinstance(escalation_id, UUID)
    assert conn.executed[0][1] == (DOC, USER.id, "Should I sue them?")


def test_write_audit_uses_keywords_and_actor_role():
    calls = []
    log = SupabaseChatLog(FakeConn(), lambda conn, **kw: calls.append(kw))
    log.write_audit(DOC, USER, "chat_turn", {"status": "answered"})
    assert calls == [
        {
            "document_id": DOC,
            "actor_id": USER.id,
            "actor_role": "startup_user",
            "action": "chat_turn",
            "details": {"status": "answered"},
        }
    ]
