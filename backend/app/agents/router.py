"""X1 stub agent endpoints. They return fixed sample output so the frontend can finish integration.

The shapes (Finding R1, chat C1) are the real ones: the real agents replace the fixtures only.
"""
from datetime import date
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.agents import service
from app.auth.dependencies import CurrentUser, get_current_user, require_role
from app.db import get_conn
from app.agents.conversational.api import ChatBody, chat_for_document, get_chat_service
from app.agents.conversational.chat_service import ChatService
from app.agents.conversational.contract import ChatResponse

router = APIRouter(prefix="/documents/{doc_id}", tags=["agents (stub)"])
startup_only = require_role("startup_user")


class DraftRequest(BaseModel):
    disclosing_party: str = Field(min_length=1, max_length=200)
    receiving_party: str = Field(min_length=1, max_length=200)
    effective_date: date
    term_months: int = Field(ge=1, le=120)
    seat: str = Field(default="Bengaluru", min_length=1, max_length=100)
    mutual: bool = True


@router.post("/review")
def review(doc_id: UUID, user: CurrentUser = Depends(startup_only), conn=Depends(get_conn)):
    return service.run_review(conn, user, doc_id)


@router.post("/chat", response_model=ChatResponse)
def chat(doc_id: UUID, body: ChatBody,
         user: CurrentUser = Depends(get_current_user), conn=Depends(get_conn),
         chat_service: ChatService = Depends(get_chat_service)):
    return chat_for_document(chat_service, conn, user, doc_id, body)


@router.post("/draft")
def draft(doc_id: UUID, body: DraftRequest,
          user: CurrentUser = Depends(startup_only), conn=Depends(get_conn)):
    return service.draft(conn, user, doc_id, body)

