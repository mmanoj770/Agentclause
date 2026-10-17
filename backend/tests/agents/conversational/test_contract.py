from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.agents.conversational.contract import (
    ChatRequest,
    ChatResponse,
    Citation,
    CitationSource,
    ReasonCode,
    TurnStatus,
)

DOC = uuid4()
CITE = Citation(source=CitationSource.DOCUMENT, chunk_id="c1", clause_number="4.2", snippet="text")


def test_request_strips_and_defaults():
    r = ChatRequest(document_id=DOC, question="  What does clause 4 mean?  ")
    assert r.question == "What does clause 4 mean?"
    assert r.language == "en"


def test_blank_question_rejected():
    with pytest.raises(ValidationError):
        ChatRequest(document_id=DOC, question="   ")


def test_non_english_rejected_for_now():
    with pytest.raises(ValidationError):
        ChatRequest(document_id=DOC, question="hi", language="hi")


def test_valid_answered():
    r = ChatResponse(document_id=DOC, status=TurnStatus.ANSWERED, answer="It means...", citations=[CITE], retrieval_score=0.82)
    assert r.status == TurnStatus.ANSWERED


def test_answered_without_citation_rejected():
    with pytest.raises(ValidationError):
        ChatResponse(document_id=DOC, status=TurnStatus.ANSWERED, answer="It means...")


def test_valid_refused():
    r = ChatResponse(document_id=DOC, status=TurnStatus.REFUSED, answer="Please consult your lawyer.", reason=ReasonCode.LOW_RETRIEVAL_SCORE)
    assert r.citations == []


def test_refused_with_advice_reason_rejected():
    with pytest.raises(ValidationError):
        ChatResponse(document_id=DOC, status=TurnStatus.REFUSED, answer="x", reason=ReasonCode.ADVICE_REQUEST)


def test_valid_escalated():
    r = ChatResponse(document_id=DOC, status=TurnStatus.ESCALATED, answer="Sent to your lawyer.", reason=ReasonCode.ADVICE_REQUEST, escalation_id=uuid4())
    assert r.escalation_id is not None


def test_escalated_with_wrong_reason_rejected():
    with pytest.raises(ValidationError):
        ChatResponse(document_id=DOC, status=TurnStatus.ESCALATED, answer="x", reason=ReasonCode.OUT_OF_SCOPE)