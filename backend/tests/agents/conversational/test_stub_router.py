from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agents.conversational.contract import ChatResponse, CitationSource, ReasonCode, TurnStatus
from app.agents.conversational.stub_router import router

app = FastAPI()
app.include_router(router)
client = TestClient(app)
DOC = uuid4()


@pytest.fixture(autouse=True)
def no_delay(monkeypatch):
    monkeypatch.setenv("CHAT_STUB_DELAY", "0")


def post(question, doc=DOC, **extra):
    return client.post(f"/documents/{doc}/chat", json={"question": question, **extra})


def parsed(question):
    response = post(question)
    assert response.status_code == 200
    return ChatResponse.model_validate(response.json())


def test_default_question_is_answered_with_citations():
    r = parsed("What is the term of this agreement?")
    assert r.status == TurnStatus.ANSWERED
    assert len(r.citations) == 3
    assert {c.source for c in r.citations} == {CitationSource.DOCUMENT, CitationSource.LAWYER_NOTE}


def test_advice_question_is_escalated_with_id():
    r = parsed("Should I sue them?")
    assert r.status == TurnStatus.ESCALATED
    assert r.escalation_id is not None


def test_off_topic_is_refused():
    r = parsed("Who won the cricket match?")
    assert r.status == TurnStatus.REFUSED
    assert r.reason == ReasonCode.OUT_OF_SCOPE


def test_unanswerable_keyword_is_refused():
    r = parsed("What is the liability cap?")
    assert r.reason == ReasonCode.LOW_RETRIEVAL_SCORE


@pytest.mark.parametrize(
    "phrase,status,reason",
    [
        ("stub:answered", TurnStatus.ANSWERED, None),
        ("stub:refused", TurnStatus.REFUSED, ReasonCode.LOW_RETRIEVAL_SCORE),
        ("stub:escalated", TurnStatus.ESCALATED, ReasonCode.ADVICE_REQUEST),
        ("stub:unrecorded", TurnStatus.ESCALATED, ReasonCode.ADVICE_REQUEST),
        ("stub:unavailable", TurnStatus.REFUSED, ReasonCode.TEMPORARILY_UNAVAILABLE),
        ("stub:notready", TurnStatus.REFUSED, ReasonCode.DOCUMENT_NOT_READY),
    ],
)
def test_forced_states(phrase, status, reason):
    r = parsed(phrase)
    assert r.status == status
    assert r.reason == reason
    if phrase == "stub:unrecorded":
        assert r.escalation_id is None


def test_blank_question_rejected():
    assert post("   ").status_code == 422


def test_invalid_document_id_rejected():
    response = client.post("/documents/not-a-uuid/chat", json={"question": "hi"})
    assert response.status_code == 422


def test_non_english_rejected():
    assert post("What is the term?", language="hi").status_code == 422


def test_document_id_is_echoed():
    other = uuid4()
    response = post("What is the term?", doc=other)
    assert response.json()["document_id"] == str(other)