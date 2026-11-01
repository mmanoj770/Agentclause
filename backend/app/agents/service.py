from fastapi import HTTPException

from app.audit import write_audit
from app.auth.dependencies import CurrentUser
from app.agents import fixtures
from app.agents.citation_gate import screen_findings
from app.documents.service import Actor, get_document, transition
from app.findings.service import insert_agent_findings
from app.documents.states import DocState

SYSTEM_ACTOR = Actor(kind="system")  # TODO(decision): a real system actor id for audit rows
REVIEWABLE = frozenset({DocState.DRAFTED, DocState.REVISION_IN_PROGRESS})
# Stub-level default: the fixtures are NDA-shaped, so no other doc_type gets a review or draft until a
# second type has a real agent. Do not mark any contract type live because of this.
STUB_DOC_TYPES = frozenset({"nda"})


def _require_stub_doc_type(doc: dict) -> None:
    if doc["doc_type"] not in STUB_DOC_TYPES:
        raise HTTPException(
            422, f"Review and drafting are only available for NDAs for now; "
                 f"this document is '{doc['doc_type']}'")


def run_review(conn, user: CurrentUser, doc_id) -> dict:
    """Stub review: fixed findings on the latest version, then hand the document to the lawyer queue.

    drafted (or revision_in_progress) -> under_ai_review -> pending_lawyer_review, all in one
    transaction so a failure cannot leave the document stuck in under_ai_review.
    """
    doc = get_document(conn, doc_id, user)  # 404 outside the caller's org
    _require_stub_doc_type(doc)
    if doc["state"] not in REVIEWABLE:
        raise HTTPException(409, f"A review cannot start while the document is '{doc['state']}'")
    version = conn.execute(
        "select id, version_no from document_versions where document_id = %s "
        "order by version_no desc limit 1", (doc_id,)).fetchone()
    if version is None:
        raise HTTPException(409, "Upload the contract before requesting a review")
    # Stub-level default: one review per version, so a repeat call cannot insert duplicate findings.
    if conn.execute("select 1 from findings where document_version_id = %s limit 1",
                    (version["id"],)).fetchone():
        raise HTTPException(409, "This version has already been reviewed; upload a revised version")

    # Layer 5 citation gate (R8): before ANY state change or insert, so a corpus failure (503) leaves the
    # document untouched and a retry starts clean. Blocked findings are never stored; each is logged to
    # audit_logs on the gate's own connection. doc_type is the document's own; the clause manifest is a
    # labelled fixture until the Drafting Agent emits one per version.
    screened = screen_findings(
        fixtures.sample_findings(), doc_id,
        document=fixtures.sample_document_context(doc["doc_type"], version["version_no"]))
    with conn.transaction():
        transition(conn, doc_id, DocState.UNDER_AI_REVIEW, SYSTEM_ACTOR, "stub review started")
        created = insert_agent_findings(conn, doc["id"], version["id"], screened.passed)
        write_audit(conn, document_id=doc_id, actor_id=None, actor_role="system",
                    action="findings_created",
                    details={"count": created, "blocked": len(screened.blocked),
                             "version_no": version["version_no"], "stub": True})
        updated = transition(conn, doc_id, DocState.PENDING_LAWYER_REVIEW, SYSTEM_ACTOR,
                             "stub review finished")
    return {"state": updated["state"], "version_no": version["version_no"],
            "findings_created": created, "findings_blocked": len(screened.blocked)}


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
