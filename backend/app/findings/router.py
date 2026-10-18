from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.auth.dependencies import CurrentUser, require_role
from app.db import get_conn
from app.findings import service
from app.findings.schemas import (AdjudicateIn, ClientFindingOut, LawyerFindingIn, LawyerFindingOut,
                                  Severity)

router = APIRouter(tags=["findings"])
lawyer_only = require_role("lawyer")
startup_only = require_role("startup_user")


@router.get("/documents/{doc_id}/findings", response_model=list[LawyerFindingOut])
def list_findings(doc_id: UUID, layer: int | None = Query(None, ge=0, le=6),
                  severity: Severity | None = None,
                  user: CurrentUser = Depends(lawyer_only), conn=Depends(get_conn)):
    return service.list_findings(conn, user, doc_id, layer, severity)


@router.post("/findings/{finding_id}/adjudicate", response_model=LawyerFindingOut)
def adjudicate(finding_id: UUID, body: AdjudicateIn,
               user: CurrentUser = Depends(lawyer_only), conn=Depends(get_conn)):
    return service.adjudicate(conn, user, finding_id, body)


@router.post("/documents/{doc_id}/findings", status_code=201, response_model=LawyerFindingOut)
def add_finding(doc_id: UUID, body: LawyerFindingIn,
                user: CurrentUser = Depends(lawyer_only), conn=Depends(get_conn)):
    return service.add_finding(conn, user, doc_id, body)


@router.get("/documents/{doc_id}/client-findings", response_model=list[ClientFindingOut])
def list_client_findings(doc_id: UUID, user: CurrentUser = Depends(startup_only), conn=Depends(get_conn)):
    return service.list_client_findings(conn, user, doc_id)
