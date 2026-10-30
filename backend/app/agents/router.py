"""X1 stub agent endpoints. They return fixed sample output so the frontend can finish integration.

The shapes (Finding R1, chat C1) are the real ones: the real agents replace the fixtures only.
"""
from datetime import date
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel, Field

from app.agents import service
from app.pipeline import runner
from app.auth.dependencies import CurrentUser, get_current_user, require_role
from app.db import get_conn

router = APIRouter(prefix="/documents/{doc_id}", tags=["agents (stub)"])
startup_only = require_role("startup_user")


class ChatRequest(BaseModel):
    document_id: UUID | None = None  # accepted for the C1 shape; the path's doc_id is what counts
    question: str = Field(min_length=1, max_length=2000)
    language: Literal["en"] = "en"  # English only for the MVP (FR-22)


class Citation(BaseModel):
    clause_reference: str
    quote: str


class ChatResponse(BaseModel):
    status: Literal["answered", "refused", "escalated"]
    answer: str | None = None       # only when answered
    citations: list[Citation] = []  # at least one when answered
    reason: str | None = None       # only when refused or escalated
    language: Literal["en"] = "en"


class DraftRequest(BaseModel):
    disclosing_party: str = Field(min_length=1, max_length=200)
    receiving_party: str = Field(min_length=1, max_length=200)
    effective_date: date
    term_months: int = Field(ge=1, le=120)
    seat: str = Field(default="Bengaluru", min_length=1, max_length=100)
    mutual: bool = True


@router.post("/review", status_code=202)
def review(doc_id: UUID, background: BackgroundTasks, user: CurrentUser = Depends(startup_only),
           conn=Depends(get_conn)):
    """Start the AI review (R10). It runs in the background; poll GET /documents/{id} for the state:
    pending_lawyer_review when it finished, back to the starting state if it failed."""
    started = runner.start_review(conn, user, doc_id)
    background.add_task(runner.run_pipeline, doc_id, started["version_id"], started["from_state"])
    return {"state": started["state"], "version_no": started["version_no"]}


@router.post("/chat", response_model=ChatResponse)
def chat(doc_id: UUID, body: ChatRequest,
         user: CurrentUser = Depends(get_current_user), conn=Depends(get_conn)):
    return service.chat_turn(conn, user, doc_id, body.question)


@router.post("/draft")
def draft(doc_id: UUID, body: DraftRequest,
          user: CurrentUser = Depends(startup_only), conn=Depends(get_conn)):
    return service.draft(conn, user, doc_id, body)
