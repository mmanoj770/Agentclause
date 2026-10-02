from dataclasses import dataclass
from decimal import Decimal

from fastapi import HTTPException

from app.audit import write_audit
from app.auth.dependencies import CurrentUser
from app.config import settings
from app.documents.states import LAWYER, STARTUP, TRANSITIONS, DocState


@dataclass
class Actor:
    kind: str                  # 'system' | 'startup_user' | 'lawyer'
    id: str | None = None
    org_id: str | None = None

    @classmethod
    def from_user(cls, user: CurrentUser) -> "Actor":
        return cls(kind=user.role, id=user.id, org_id=user.org_id)


def _can_view(doc: dict, actor: Actor) -> bool:
    # This connection bypasses RLS, so the service must enforce visibility itself.
    if actor.kind == STARTUP:
        return actor.org_id is not None and str(doc["org_id"]) == actor.org_id
    if actor.kind == LAWYER:
        return doc["assigned_lawyer_id"] is not None and str(doc["assigned_lawyer_id"]) == actor.id
    return False


def create_document(conn, user: CurrentUser, doc_type: str,
                    state_of_execution: str | None, transaction_value: Decimal | None) -> dict:
    if user.org_id is None:
        raise HTTPException(400, "Your account is not linked to an organization yet")
    with conn.transaction():
        ct = conn.execute(
            "select status from contract_types where code = %s", (doc_type,)
        ).fetchone()
        if ct is None:
            raise HTTPException(422, f"Unknown contract type '{doc_type}'")
        if ct["status"] not in settings.selectable_contract_statuses:
            raise HTTPException(422, f"'{doc_type}' is not supported yet")
        doc = conn.execute(
            """insert into documents (org_id, created_by, doc_type, state_of_execution, transaction_value)
               values (%s, %s, %s, %s, %s) returning *""",
            (user.org_id, user.id, doc_type, state_of_execution, transaction_value),
        ).fetchone()
        write_audit(conn, document_id=doc["id"], actor_id=user.id, actor_role=user.role,
                    action="document_created", details={"doc_type": doc_type})
    return doc


def list_documents(conn, user: CurrentUser) -> list[dict]:
    if user.role == STARTUP:
        if user.org_id is None:
            return []
        return conn.execute(
            "select * from documents where org_id = %s order by created_at desc", (user.org_id,)
        ).fetchall()
    return conn.execute(
        "select * from documents where assigned_lawyer_id = %s order by created_at desc", (user.id,)
    ).fetchall()


def get_document(conn, doc_id, user: CurrentUser) -> dict:
    doc = conn.execute("select * from documents where id = %s", (doc_id,)).fetchone()
    if doc is None or not _can_view(doc, Actor.from_user(user)):
        raise HTTPException(404, "Document not found")  # same answer either way: no leaking
    return doc


def transition(conn, doc_id, to_state: DocState, actor: Actor, note: str | None = None) -> dict:
    with conn.transaction():
        # Lock the row so two simultaneous requests can't both change the state
        doc = conn.execute(
            "select * from documents where id = %s for update", (doc_id,)
        ).fetchone()
        if doc is None or (actor.kind != "system" and not _can_view(doc, actor)):
            raise HTTPException(404, "Document not found")

        from_state = doc["state"]
        allowed = TRANSITIONS.get((from_state, to_state))
        if allowed is None:
            raise HTTPException(409, f"Cannot move from '{from_state}' to '{to_state.value}'")
        if actor.kind not in allowed:
            raise HTTPException(403, "Your role cannot make this change")

        draft_flag = doc["draft_for_settlement"]

        if to_state == DocState.LAWYER_APPROVED:
            # Sign-off: the one legally accountable act
            signed = conn.execute(
                """update lawyer_assignments set signed_off_at = now()
                   where document_id = %s and lawyer_id = %s and signed_off_at is null
                   returning id""",
                (doc_id, actor.id),
            ).fetchone()
            if signed is None:
                raise HTTPException(409, "No active assignment for this lawyer on this document")
            draft_flag = False

        if to_state == DocState.DELIVERED:
            # Hard block: nothing leaves without sign-off
            ok = conn.execute(
                "select 1 from lawyer_assignments where document_id = %s and signed_off_at is not null",
                (doc_id,),
            ).fetchone()
            if draft_flag or ok is None:
                raise HTTPException(409, "Document has no lawyer sign-off; delivery blocked")

        updated = conn.execute(
            """update documents
               set state = %s,
                   draft_for_settlement = %s,
                   queued_at = case when %s::boolean then now() else queued_at end
               where id = %s returning *""",
            (to_state.value, draft_flag, to_state == DocState.PENDING_LAWYER_REVIEW, doc_id),
        ).fetchone()

        write_audit(
            conn, document_id=doc_id, actor_id=actor.id, actor_role=actor.kind,
            action="state_change",
            details={"from": str(from_state), "to": to_state.value, "note": note},
        )
    return updated
