from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.auth.dependencies import CurrentUser, require_role
from app.db import get_conn
from app.lawyer_queue import service

router = APIRouter(prefix="/queue", tags=["lawyer queue"])
lawyer_only = require_role("lawyer")


class ConflictRequest(BaseModel):
    reason: str | None = None


@router.get("")
def list_queue(limit: int = Query(50, ge=1, le=100),
               user: CurrentUser = Depends(lawyer_only), conn=Depends(get_conn)):
    return service.list_queue(conn, user, limit)


@router.post("/{doc_id}/claim")
def claim(doc_id: UUID, user: CurrentUser = Depends(lawyer_only), conn=Depends(get_conn)):
    return service.claim(conn, user, doc_id)


@router.post("/{doc_id}/release")
def release(doc_id: UUID, user: CurrentUser = Depends(lawyer_only), conn=Depends(get_conn)):
    return service.release(conn, user, doc_id)


@router.post("/{doc_id}/declare-conflict")
def declare_conflict(doc_id: UUID, body: ConflictRequest,
                     user: CurrentUser = Depends(lawyer_only), conn=Depends(get_conn)):
    return service.declare_conflict(conn, user, doc_id, body.reason)
