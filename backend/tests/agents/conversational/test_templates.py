from uuid import uuid4

import pytest

from app.agents.conversational.contract import ReasonCode, TurnStatus
from app.agents.conversational.templates import (
    ESCALATION_RECORDED_TEXT,
    ESCALATION_UNRECORDED_TEXT,
    REFUSAL_TEXT,
    InMemoryEscalationStore,
    build_escalation,
    build_refusal,
)

DOC = uuid4()


class FailingStore:
    def create(self, document_id, question):
        raise RuntimeError("db down")


def test_every_non_advice_reason_has_text():
    for reason in ReasonCode:
        if reason != ReasonCode.ADVICE_REQUEST:
            assert REFUSAL_TEXT[reason].strip()


def test_refusals_are_refused_with_no_citations():
    for reason in REFUSAL_TEXT:
        response = build_refusal(DOC, reason)
        assert response.status == TurnStatus.REFUSED
        assert response.reason == reason
        assert response.citations == []
        assert response.answer == REFUSAL_TEXT[reason]


def test_refusal_score_is_clamped():
    assert build_refusal(DOC, ReasonCode.LOW_RETRIEVAL_SCORE, retrieval_score=-0.2).retrieval_score == 0.0
    assert build_refusal(DOC, ReasonCode.LOW_RETRIEVAL_SCORE, retrieval_score=0.31).retrieval_score == 0.31


def test_advice_reason_not_allowed_in_build_refusal():
    with pytest.raises(ValueError):
        build_refusal(DOC, ReasonCode.ADVICE_REQUEST)


def test_escalation_records_question_and_returns_id():
    store = InMemoryEscalationStore()
    response = build_escalation(DOC, "Should I sue them?", store)
    assert response.status == TurnStatus.ESCALATED
    assert response.reason == ReasonCode.ADVICE_REQUEST
    assert response.answer == ESCALATION_RECORDED_TEXT
    assert len(store.records) == 1
    assert store.records[0].escalation_id == response.escalation_id
    assert store.records[0].document_id == DOC
    assert store.records[0].question == "Should I sue them?"


def test_failed_store_still_escalates_without_claiming_it_was_sent():
    response = build_escalation(DOC, "Should I sue them?", FailingStore())
    assert response.status == TurnStatus.ESCALATED
    assert response.escalation_id is None
    assert response.answer == ESCALATION_UNRECORDED_TEXT
    assert "passed your question on" not in response.answer