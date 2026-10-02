from fastapi import HTTPException
from psycopg.errors import UniqueViolation

from app.audit import write_audit
from app.auth.dependencies import CurrentUser

# Every lawyer gets the same list in the same order (oldest first).
# The only per-lawyer filter is hiding clients they declared a conflict with.
# Never add ranking, scoring or "suggested lawyer" logic here (BCI Rule 36).
QUEUE_SQL = """
select d.id, d.doc_type, d.state_of_execution, d.transaction_value,
       d.triage_tier, d.queued_at, o.id as org_id, o.name as org_name
from documents d
join organizations o on o.id = d.org_id
where d.state = 'pending_lawyer_review'
  and d.assigned_lawyer_id is null
  and not exists (
    select 1 from lawyer_conflicts c
    where c.lawyer_id = %s and c.org_id = d.org_id
  )
order by d.queued_at asc, d.id asc
limit %s
"""


def list_queue(conn, user: CurrentUser, limit: int = 50) -> list[dict]:
    return conn.execute(QUEUE_SQL, (user.id, limit)).fetchall()


def claim(conn, user: CurrentUser, doc_id) -> dict:
    try:
        with conn.transaction():
            doc = conn.execute(
                "select * from documents where id = %s for update", (doc_id,)
            ).fetchone()
            if doc is None:
                raise HTTPException(404, "Document not found")
            if doc["state"] != "pending_lawyer_review" or doc["assigned_lawyer_id"] is not None:
                raise HTTPException(409, "This document is no longer available")

            conflict = conn.execute(
                "select 1 from lawyer_conflicts where lawyer_id = %s and org_id = %s",
                (user.id, doc["org_id"]),
            ).fetchone()
            if conflict:
                raise HTTPException(409, "You have declared a conflict with this client")

            updated = conn.execute(
                "update documents set assigned_lawyer_id = %s where id = %s returning *",
                (user.id, doc_id),
            ).fetchone()
            conn.execute(
                "insert into lawyer_assignments (document_id, lawyer_id) values (%s, %s)",
                (doc_id, user.id),
            )
            write_audit(conn, document_id=doc_id, actor_id=user.id, actor_role=user.role,
                        action="document_claimed")
        return updated
    except UniqueViolation:
        raise HTTPException(409, "This document is no longer available")


def _release_locked(conn, user: CurrentUser, doc_id) -> None:
    conn.execute(
        "delete from lawyer_assignments where document_id = %s and lawyer_id = %s",
        (doc_id, user.id),
    )
    conn.execute("update documents set assigned_lawyer_id = null where id = %s", (doc_id,))


def release(conn, user: CurrentUser, doc_id) -> dict:
    with conn.transaction():
        doc = conn.execute(
            "select * from documents where id = %s for update", (doc_id,)
        ).fetchone()
        if doc is None or str(doc["assigned_lawyer_id"]) != user.id:
            raise HTTPException(404, "Document not found")
        if doc["state"] != "pending_lawyer_review":
            raise HTTPException(409, "You can only release a document before you act on it")
        _release_locked(conn, user, doc_id)
        write_audit(conn, document_id=doc_id, actor_id=user.id, actor_role=user.role,
                    action="document_released")
    return {"ok": True}


def declare_conflict(conn, user: CurrentUser, doc_id, reason: str | None) -> dict:
    with conn.transaction():
        doc = conn.execute(
            "select * from documents where id = %s for update", (doc_id,)
        ).fetchone()
        mine = doc is not None and str(doc["assigned_lawyer_id"]) == user.id
        in_queue = doc is not None and doc["assigned_lawyer_id"] is None
        if doc is None or doc["state"] != "pending_lawyer_review" or not (mine or in_queue):
            raise HTTPException(404, "Document not found")

        conn.execute(
            """insert into lawyer_conflicts (lawyer_id, org_id, reason) values (%s, %s, %s)
               on conflict (lawyer_id, org_id) do nothing""",
            (user.id, doc["org_id"], reason),
        )
        if mine:
            _release_locked(conn, user, doc_id)
        write_audit(conn, document_id=doc_id, actor_id=user.id, actor_role=user.role,
                    action="conflict_declared",
                    details={"org_id": str(doc["org_id"]), "reason": reason})
    return {"ok": True}
