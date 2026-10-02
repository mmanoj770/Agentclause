from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.auth.dependencies import CurrentUser, get_current_user, require_role
from app.db import get_conn
from app.documents import service
from app.documents.service import Actor
from app.documents.states import DocState

router = APIRouter(prefix="/documents", tags=["documents"])


class CreateDocument(BaseModel):
    doc_type: str
    state_of_execution: str | None = None
    transaction_value: Decimal | None = Field(default=None, ge=0)


class TransitionRequest(BaseModel):
    to_state: DocState
    note: str | None = None


@router.post("", status_code=201)
def create(body: CreateDocument, user: CurrentUser = Depends(require_role("startup_user")),
           conn=Depends(get_conn)):
    return service.create_document(conn, user, body.doc_type,
                                   body.state_of_execution, body.transaction_value)


@router.get("")
def list_all(user: CurrentUser = Depends(get_current_user), conn=Depends(get_conn)):
    return service.list_documents(conn, user)


@router.get("/{doc_id}")
def get_one(doc_id: UUID, user: CurrentUser = Depends(get_current_user), conn=Depends(get_conn)):
    return service.get_document(conn, doc_id, user)


@router.post("/{doc_id}/transition")
def change_state(doc_id: UUID, body: TransitionRequest,
                 user: CurrentUser = Depends(get_current_user), conn=Depends(get_conn)):
    return service.transition(conn, doc_id, body.to_state, Actor.from_user(user), body.note)
