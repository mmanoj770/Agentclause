"""Tenancy checks in chunk_service, against an in-memory stand-in for the database
(migration 19 is not applied yet, so there is no document_chunks table to hit)."""

import pytest
from fastapi import HTTPException

from app.auth.dependencies import CurrentUser
from app.documents.chunk_service import get_chunks_for_version

ORG_A, ORG_B = "org-a", "org-b"
DOC_A, DOC_B = "doc-a", "doc-b"
VER_A, VER_B = "ver-a", "ver-b"
LAWYER, OTHER_LAWYER = "lawyer-1", "lawyer-2"

DOCUMENTS = {
    DOC_A: {"id": DOC_A, "org_id": ORG_A, "assigned_lawyer_id": LAWYER, "state": "pending_lawyer_review"},
    DOC_B: {"id": DOC_B, "org_id": ORG_B, "assigned_lawyer_id": None, "state": "pending_lawyer_review"},
}
VERSIONS = {VER_A: DOC_A, VER_B: DOC_B}
CHUNKS = {VER_A: [{"id": "c1", "chunk_index": 0, "text": "Org A clause"}],
          VER_B: [{"id": "c2", "chunk_index": 0, "text": "Org B clause"}]}


class FakeResult:
    def __init__(self, rows):
        self.rows = rows

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


class FakeConn:
    def __init__(self, documents=DOCUMENTS):
        self.documents = documents

    def execute(self, sql, params):
        if "from documents" in sql:
            doc = self.documents.get(params[0])
            return FakeResult([doc] if doc else [])
        if "from document_versions" in sql:
            ver, doc = params
            return FakeResult([{"id": ver}] if VERSIONS.get(ver) == doc else [])
        if "from document_chunks" in sql:
            doc, ver = params
            return FakeResult(CHUNKS.get(ver, []) if VERSIONS.get(ver) == doc else [])
        raise AssertionError(f"unexpected query: {sql}")


def startup(org_id):
    return CurrentUser(id="user-1", email=None, role="startup_user", org_id=org_id)


def lawyer(user_id):
    return CurrentUser(id=user_id, email=None, role="lawyer", org_id=None)


def assert_not_found(user, doc, ver, conn=None):
    with pytest.raises(HTTPException) as exc:
        get_chunks_for_version(conn or FakeConn(), user, doc, ver)
    assert exc.value.status_code == 404


def test_own_org_gets_chunks():
    assert get_chunks_for_version(FakeConn(), startup(ORG_A), DOC_A, VER_A) == CHUNKS[VER_A]


def test_assigned_lawyer_gets_chunks():
    assert get_chunks_for_version(FakeConn(), lawyer(LAWYER), DOC_A, VER_A) == CHUNKS[VER_A]


def test_cross_org_blocked():
    assert_not_found(startup(ORG_B), DOC_A, VER_A)


@pytest.mark.parametrize("org_id", [None, ""])
def test_null_or_empty_org_blocked(org_id):
    assert_not_found(startup(org_id), DOC_A, VER_A)


def test_unassigned_lawyer_blocked():
    assert_not_found(lawyer(OTHER_LAWYER), DOC_A, VER_A)


def test_lawyer_blocked_on_unassigned_document():
    assert_not_found(lawyer(LAWYER), DOC_B, VER_B)


def test_version_from_another_document_blocked():
    # Allowed document, but a version id belonging to org B's document.
    assert_not_found(startup(ORG_A), DOC_A, VER_B)


def test_unknown_document_blocked():
    assert_not_found(startup(ORG_A), "no-such-doc", VER_A)


@pytest.mark.parametrize("state", ["drafted", "under_ai_review"])
def test_chat_blocked_before_review_finishes(state):
    docs = {**DOCUMENTS, DOC_A: {**DOCUMENTS[DOC_A], "state": state}}
    with pytest.raises(HTTPException) as exc:
        get_chunks_for_version(FakeConn(docs), startup(ORG_A), DOC_A, VER_A)
    assert exc.value.status_code == 409
