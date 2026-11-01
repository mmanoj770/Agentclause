from enum import Enum
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator, model_validator


class TurnStatus(str, Enum):
    ANSWERED = "answered"
    REFUSED = "refused"
    ESCALATED = "escalated"


class ReasonCode(str, Enum):
    ADVICE_REQUEST = "advice_request"
    LOW_RETRIEVAL_SCORE = "low_retrieval_score"
    UNSUPPORTED_BY_SOURCE = "unsupported_by_source"
    OUT_OF_SCOPE = "out_of_scope"
    DOCUMENT_NOT_READY = "document_not_ready"
    TEMPORARILY_UNAVAILABLE = "temporarily_unavailable"
    DOCUMENT_UNREADABLE = "document_unreadable"


class CitationSource(str, Enum):
    DOCUMENT = "document"
    LAWYER_NOTE = "lawyer_note"


class Citation(BaseModel):
    source: CitationSource
    chunk_id: str
    clause_number: str | None = None
    heading: str | None = None
    snippet: str = Field(max_length=500)


class ChatRequest(BaseModel):
    document_id: UUID
    question: str = Field(min_length=1, max_length=1000)
    language: Literal["en"] = "en"

    @field_validator("question")
    @classmethod
    def strip_question(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("question must not be blank")
        return v


class ChatResponse(BaseModel):
    turn_id: UUID = Field(default_factory=uuid4)
    document_id: UUID
    status: TurnStatus
    answer: str = Field(min_length=1)
    citations: list[Citation] = Field(default_factory=list)
    reason: ReasonCode | None = None
    retrieval_score: float | None = Field(default=None, ge=0.0, le=1.0)
    escalation_id: UUID | None = None

    @model_validator(mode="after")
    def check_status_rules(self) -> "ChatResponse":
        if self.status == TurnStatus.ANSWERED:
            if not self.citations:
                raise ValueError("answered turns need at least one citation")
            if self.reason is not None or self.escalation_id is not None:
                raise ValueError("answered turns cannot carry a reason or escalation_id")
        elif self.status == TurnStatus.REFUSED:
            if self.citations:
                raise ValueError("refused turns cannot carry citations")
            if self.reason is None or self.reason == ReasonCode.ADVICE_REQUEST:
                raise ValueError("refused turns need a non-advice reason code")
        elif self.status == TurnStatus.ESCALATED:
            if self.citations:
                raise ValueError("escalated turns cannot carry citations")
            if self.reason != ReasonCode.ADVICE_REQUEST:
                raise ValueError("escalated turns must use reason advice_request")
        return self