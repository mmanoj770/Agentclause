import logging
from datetime import datetime, timezone
from typing import Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from app.agents.conversational.contract import ChatResponse, ReasonCode, TurnStatus
from app.agents.conversational.gates import clamp_score

log = logging.getLogger(__name__)

REFUSAL_TEXT: dict[ReasonCode, str] = {
    ReasonCode.LOW_RETRIEVAL_SCORE: (
        "I couldn't find anything in your document that answers this, and I won't guess. "
        "Please ask your advocate."
    ),
    ReasonCode.UNSUPPORTED_BY_SOURCE: (
        "I couldn't confirm an answer against the text of your document, so I'm not going to give one. "
        "Please read the clause directly or ask your advocate."
    ),
    ReasonCode.OUT_OF_SCOPE: (
        "I can only answer questions about your contract and your advocate's notes on it."
    ),
    ReasonCode.DOCUMENT_NOT_READY: (
        "This document isn't ready for questions yet. Chat opens once your advocate has signed it off."
    ),
}

ESCALATION_RECORDED_TEXT = (
    "That question is about your own situation, and answering it would be legal advice, "
    "which only your advocate can give. I've passed your question on to your advocate."
)
ESCALATION_UNRECORDED_TEXT = (
    "That question is about your own situation, and answering it would be legal advice, "
    "which only your advocate can give. Please contact your advocate directly with this question."
)


class EscalationRecord(BaseModel):
    escalation_id: UUID
    document_id: UUID
    question: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class EscalationStore(Protocol):
    def create(self, document_id: UUID, question: str) -> UUID: ...


class InMemoryEscalationStore:
    def __init__(self) -> None:
        self.records: list[EscalationRecord] = []

    def create(self, document_id: UUID, question: str) -> UUID:
        record = EscalationRecord(
            escalation_id=uuid4(), document_id=document_id, question=question
        )
        self.records.append(record)
        return record.escalation_id


def build_refusal(
    document_id: UUID, reason: ReasonCode, retrieval_score: float | None = None
) -> ChatResponse:
    if reason == ReasonCode.ADVICE_REQUEST:
        raise ValueError("advice requests are escalated, use build_escalation")
    return ChatResponse(
        document_id=document_id,
        status=TurnStatus.REFUSED,
        answer=REFUSAL_TEXT[reason],
        reason=reason,
        retrieval_score=None if retrieval_score is None else clamp_score(retrieval_score),
    )


def build_escalation(
    document_id: UUID, question: str, store: EscalationStore
) -> ChatResponse:
    try:
        escalation_id = store.create(document_id, question)
    except Exception:
        log.exception("could not record escalation")
        escalation_id = None
    return ChatResponse(
        document_id=document_id,
        status=TurnStatus.ESCALATED,
        answer=ESCALATION_RECORDED_TEXT if escalation_id else ESCALATION_UNRECORDED_TEXT,
        reason=ReasonCode.ADVICE_REQUEST,
        escalation_id=escalation_id,
    )