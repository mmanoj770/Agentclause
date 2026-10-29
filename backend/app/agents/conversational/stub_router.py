import os
import time
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ValidationError

from app.agents.conversational.classifier import matches_advice_rule
from app.agents.conversational.contract import (
    ChatRequest,
    ChatResponse,
    Citation,
    CitationSource,
    ReasonCode,
    TurnStatus,
)
from app.agents.conversational.templates import (
    ESCALATION_RECORDED_TEXT,
    ESCALATION_UNRECORDED_TEXT,
    REFUSAL_TEXT,
)

router = APIRouter(tags=["conversational-stub"])

OFF_TOPIC_WORDS = {"cricket", "weather", "joke", "recipe", "biryani", "movie", "football"}
UNANSWERABLE_WORDS = {"liability", "indemnity", "payment", "non-compete", "force majeure", "insurance"}

SAMPLE_ANSWER = (
    "The term of this agreement is five years from the effective date. "
    "Your confidentiality obligations continue for ten years after the term ends. "
    "Your advocate noted that this period is standard for this type of agreement."
)
SAMPLE_CITATIONS = [
    Citation(
        source=CitationSource.DOCUMENT,
        chunk_id="stub:9",
        clause_number="9",
        heading="Term",
        snippet="The Term of this agreement is Five (5) years from the date of signing.",
    ),
    Citation(
        source=CitationSource.DOCUMENT,
        chunk_id="stub:5",
        clause_number="5",
        heading="Confidentiality Period",
        snippet="For the term of this Agreement and Ten (10) years thereafter.",
    ),
    Citation(
        source=CitationSource.LAWYER_NOTE,
        chunk_id="stub:note:0",
        clause_number=None,
        heading="Lawyer note",
        snippet="Sample advocate note: the ten year period is acceptable.",
    ),
]


class ChatBody(BaseModel):
    question: str
    language: str = "en"


def _answered(document_id: UUID) -> ChatResponse:
    return ChatResponse(
        document_id=document_id,
        status=TurnStatus.ANSWERED,
        answer=SAMPLE_ANSWER,
        citations=SAMPLE_CITATIONS,
        retrieval_score=0.66,
    )


def _refused(document_id: UUID, reason: ReasonCode, score: float | None = None) -> ChatResponse:
    return ChatResponse(
        document_id=document_id,
        status=TurnStatus.REFUSED,
        answer=REFUSAL_TEXT[reason],
        reason=reason,
        retrieval_score=score,
    )


def _escalated(document_id: UUID, recorded: bool = True) -> ChatResponse:
    return ChatResponse(
        document_id=document_id,
        status=TurnStatus.ESCALATED,
        answer=ESCALATION_RECORDED_TEXT if recorded else ESCALATION_UNRECORDED_TEXT,
        reason=ReasonCode.ADVICE_REQUEST,
        escalation_id=uuid4() if recorded else None,
    )


def stub_response(document_id: UUID, question: str) -> ChatResponse:
    q = question.strip().lower()

    if q.startswith("stub:answered"):
        return _answered(document_id)
    if q.startswith("stub:refused"):
        return _refused(document_id, ReasonCode.LOW_RETRIEVAL_SCORE, 0.21)
    if q.startswith("stub:escalated"):
        return _escalated(document_id)
    if q.startswith("stub:unrecorded"):
        return _escalated(document_id, recorded=False)
    if q.startswith("stub:unavailable"):
        return _refused(document_id, ReasonCode.TEMPORARILY_UNAVAILABLE)
    if q.startswith("stub:notready"):
        return _refused(document_id, ReasonCode.DOCUMENT_NOT_READY)

    if matches_advice_rule(question):
        return _escalated(document_id)
    if any(word in q for word in OFF_TOPIC_WORDS):
        return _refused(document_id, ReasonCode.OUT_OF_SCOPE)
    if any(word in q for word in UNANSWERABLE_WORDS):
        return _refused(document_id, ReasonCode.LOW_RETRIEVAL_SCORE, 0.28)
    return _answered(document_id)


@router.post("/documents/{document_id}/chat", response_model=ChatResponse)
def chat(document_id: UUID, body: ChatBody) -> ChatResponse:
    try:
        request = ChatRequest(
            document_id=document_id, question=body.question, language=body.language
        )
    except ValidationError as exc:
        detail = [{"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()]
        raise HTTPException(status_code=422, detail=detail)

    time.sleep(float(os.environ.get("CHAT_STUB_DELAY", "0.6")))
    return stub_response(request.document_id, request.question)