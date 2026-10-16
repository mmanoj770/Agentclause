from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.auth.dependencies import CurrentUser, require_role
from app.db import get_conn
from app.findings import service
from app.findings.schemas import AdjudicateIn, LawyerFindingIn, Severity

router = APIRouter(tags=["findings"])
lawyer_only = require_role("lawyer")


@router.get("/documents/{doc_id}/findings")
def list_findings(doc_id: UUID, layer: int | None = Query(None, ge=0, le=6),
                  severity: Severity | None = None,
                  user: CurrentUser = Depends(lawyer_only), conn=Depends(get_conn)):
    return service.list_findings(conn, user, doc_id, layer, severity)


@router.post("/findings/{finding_id}/adjudicate")
def adjudicate(finding_id: UUID, body: AdjudicateIn,
               user: CurrentUser = Depends(lawyer_only), conn=Depends(get_conn)):
    return service.adjudicate(conn, user, finding_id, body)


@router.post("/documents/{doc_id}/findings", status_code=201)
def add_finding(doc_id: UUID, body: LawyerFindingIn,
                user: CurrentUser = Depends(lawyer_only), conn=Depends(get_conn)):
    return service.add_finding(conn, user, doc_id, body)
