from fastapi import HTTPException

from app.audit import write_audit
from app.auth.dependencies import CurrentUser
from app.documents.service import get_document
from app.agents.citation_gate import PassedFinding
from app.documents.states import DocState
from app.findings.schemas import AdjudicateIn, ClientFindingOut, LawyerFindingIn
from app.schemas.finding import INSERT_COLUMNS, FindingOrigin


def insert_agent_findings(conn, document_id, version_id, passed: list[PassedFinding]) -> int:
    """The one place agent findings are written (not exposed as an API route).

    It takes only what the Layer 5 citation gate passed (`GateResult.passed`), never raw findings,
    so an unscreened finding cannot be stored by mistake. Runs inside the caller's transaction and
    writes no audit row; the caller records `findings_created`. Every column, including `citation`
    and `citation_type`, comes from the Finding model (INSERT_COLUMNS).
    """
    ok = conn.execute(
        "select 1 from document_versions where id = %s and document_id = %s",
        (version_id, document_id),
    ).fetchone()
    if ok is None:
        raise ValueError("version does not belong to this document")
    columns = ", ".join(INSERT_COLUMNS)
    marks = ", ".join(["%s"] * len(INSERT_COLUMNS))
    for p in passed:
        if p.finding.origin is not FindingOrigin.AGENT:
            raise ValueError("only agent-origin findings are written here; lawyer-added findings have their own route")
        row = p.finding.to_insert_row(document_id, version_id)
        conn.execute(f"insert into findings ({columns}) values ({marks})", tuple(row[c] for c in INSERT_COLUMNS))
    return len(passed)


def list_findings(conn, user: CurrentUser, doc_id, layer: int | None, severity: str | None):
    get_document(conn, doc_id, user)  # 404 unless this lawyer is assigned to the document
    return conn.execute(
        """select f.*, v.version_no
           from findings f
           join document_versions v on v.id = f.document_version_id
           where f.document_id = %s
             and v.version_no = (select max(version_no) from document_versions where document_id = %s)
             and (%s::smallint is null or f.layer = %s)
             and (%s::text is null or f.severity = %s)
           order by array_position(array['critical','high','medium','low'], f.severity),
                    f.layer nulls last, f.created_at""",
        (doc_id, doc_id, layer, layer, severity, severity),
    ).fetchall()


def adjudicate(conn, user: CurrentUser, finding_id, body: AdjudicateIn) -> dict:
    with conn.transaction():
        row = conn.execute(
            """select f.*, d.state as doc_state, d.assigned_lawyer_id
               from findings f join documents d on d.id = f.document_id
               where f.id = %s for update of f, d""",
            (finding_id,),
        ).fetchone()
        if row is None or str(row["assigned_lawyer_id"]) != user.id:
            raise HTTPException(404, "Finding not found")
        if row["doc_state"] != "pending_lawyer_review":
            raise HTTPException(409, "Findings can only be adjudicated while the document is in review")
        if body.action == "override" and not (body.notes and body.notes.strip()):
            raise HTTPException(422, "An override needs a reason in notes")

        updated = conn.execute(
            """update findings set advocate_action = %s, advocate_notes = %s,
                   adjudicated_by = %s, adjudicated_at = now()
               where id = %s returning *""",
            (body.action, body.notes, user.id, finding_id),
        ).fetchone()
        write_audit(conn, document_id=row["document_id"], actor_id=user.id, actor_role=user.role,
                    action="finding_adjudicated",
                    details={"finding_id": str(finding_id), "action": body.action,
                             "before": row["advocate_action"], "notes": body.notes})
    return updated


def add_finding(conn, user: CurrentUser, doc_id, body: LawyerFindingIn) -> dict:
    with conn.transaction():
        doc = conn.execute(
            "select * from documents where id = %s for update", (doc_id,)
        ).fetchone()
        if doc is None or str(doc["assigned_lawyer_id"]) != user.id:
            raise HTTPException(404, "Document not found")
        if doc["state"] != "pending_lawyer_review":
            raise HTTPException(409, "Findings can only be added while the document is in review")
        ver = conn.execute(
            "select id from document_versions where document_id = %s order by version_no desc limit 1",
            (doc_id,),
        ).fetchone()
        if ver is None:
            raise HTTPException(409, "Document has no version yet")

        created = conn.execute(
            """insert into findings (document_id, document_version_id, layer, severity,
                   clause_reference, description, rule_applied, remedy_suggested,
                   advocate_action, advocate_notes, adjudicated_by, adjudicated_at)
               values (%s, %s, null, %s, %s, %s, %s, %s, 'add', %s, %s, now())
               returning *""",
            (doc_id, ver["id"], body.severity, body.clause_reference, body.description,
             body.rule_applied, body.remedy_suggested, body.notes, user.id),
        ).fetchone()
        write_audit(conn, document_id=doc_id, actor_id=user.id, actor_role=user.role,
                    action="finding_added", details={"finding_id": str(created["id"])})
    return created


# What a client may see: lawyer-confirmed agent findings and lawyer-added ones. Pending and overridden
# findings are never shown. Checked here as well as in the query, so a changed query cannot widen it.
_CLIENT_VISIBLE = {"confirm": ("confirmed", "agent"), "add": ("added", "advocate")}
_CLIENT_VISIBLE_STATES = (DocState.LAWYER_APPROVED.value, DocState.DELIVERED.value)


def list_client_findings(conn, user: CurrentUser, doc_id) -> list[ClientFindingOut]:
    doc = get_document(conn, doc_id, user)  # first: org-scoped, 404 for anyone else (no state leak)
    if doc["state"] not in _CLIENT_VISIBLE_STATES:
        raise HTTPException(409, "Findings are available once a lawyer has signed off the document")
    # Columns are listed on purpose: layer, rule_applied and advocate_notes are never selected.
    rows = conn.execute(
        """select f.id, f.severity, f.clause_reference, f.description, f.remedy_suggested,
                  f.citation, f.citation_type, f.advocate_action
           from findings f
           join document_versions v on v.id = f.document_version_id
           where f.document_id = %s
             and v.version_no = (select max(version_no) from document_versions where document_id = %s)
             and f.advocate_action in ('confirm', 'add')
           order by array_position(array['critical','high','medium','low'], f.severity),
                    f.created_at""",
        (doc_id, doc_id),
    ).fetchall()
    out = []
    for r in rows:
        visible = _CLIENT_VISIBLE.get(r["advocate_action"])
        if visible is None:
            continue
        status, origin = visible
        out.append(ClientFindingOut(
            finding_id=r["id"], severity=r["severity"], clause_reference=r["clause_reference"],
            description=r["description"], remedy_suggested=r["remedy_suggested"],
            citation=r["citation"], citation_type=r["citation_type"], status=status, origin=origin))
    return out
