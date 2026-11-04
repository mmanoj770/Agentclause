from fastapi import HTTPException

from app.audit import write_audit
from app.auth.dependencies import CurrentUser
from app.agents import fixtures
from app.documents.service import Actor, get_document, transition
from app.documents.states import DocState

SYSTEM_ACTOR = Actor(kind="system")  # TODO(decision): a real system actor id for audit rows
REVIEWABLE = frozenset({DocState.DRAFTED, DocState.REVISION_IN_PROGRESS})
# Stub-level default: the drafting fixtures are NDA-shaped, so no other doc_type gets a draft until a
# second type has a real agent. (Reviews run the real pipeline: app/pipeline/runner.py.) Do not mark any contract type live because of this.
STUB_DOC_TYPES = frozenset({"nda"})


def _require_stub_doc_type(doc: dict) -> None:
    if doc["doc_type"] not in STUB_DOC_TYPES:
        raise HTTPException(
            422, f"Drafting is only available for NDAs for now; "
                 f"this document is '{doc['doc_type']}'")


def chat_turn(conn, user: CurrentUser, doc_id, question: str) -> dict:
    # TODO(decision, C1): the real agent talks only about a settled document; the stub answers in any state.
    get_document(conn, doc_id, user)  # startup user of the org, or the assigned lawyer; else 404
    reply = fixtures.chat_reply(question)
    write_audit(conn, document_id=doc_id, actor_id=user.id, actor_role=user.role,
                action="chat_turn", details={"question_length": len(question), "status": reply["status"], "stub": True})
    return reply


def draft(conn, user: CurrentUser, doc_id, facts) -> dict:
    doc = get_document(conn, doc_id, user)
    _require_stub_doc_type(doc)
    if doc["state"] not in REVIEWABLE:
        raise HTTPException(409, f"A draft cannot be made while the document is '{doc['state']}'")
    result = fixtures.sample_draft(facts.disclosing_party, facts.receiving_party,
                                   facts.effective_date.isoformat(), facts.term_months,
                                   facts.seat, facts.mutual)
    write_audit(conn, document_id=doc_id, actor_id=user.id, actor_role=user.role,
                action="draft_generated", details={"stub": True})
    return result
