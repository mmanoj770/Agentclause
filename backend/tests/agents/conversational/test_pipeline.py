import json
from uuid import uuid4

from app.agents.conversational.classifier import SYSTEM_PROMPT as CLASSIFIER_PROMPT
from app.agents.conversational.contract import ChatRequest, ReasonCode, TurnStatus
from app.agents.conversational.embeddings import HashEmbedder
from app.agents.conversational.generation import SYSTEM_PROMPT as GENERATION_PROMPT
from app.agents.conversational.ingest import ingest_contract
from app.agents.conversational.pipeline import ConversationalPipeline
from app.agents.conversational.retrieval import DocumentIndex
from app.agents.conversational.templates import InMemoryEscalationStore

SAMPLE = """1. Term
1.1 The Term of this agreement is five years from the effective date.

2. Governing Law
2.1 This Agreement is governed by the laws of India.
"""

GOOD = json.dumps({"answerable": True, "claims": [{"text": "The term is five years.", "sources": [1]}]})
NOT_ANSWERABLE = json.dumps({"answerable": False, "claims": []})


class RouterLLM:
    def __init__(self, label="explain", generations=None, classifier_error=False, generation_error=False):
        self.label = label
        self.generations = list(generations or [])
        self.classifier_error = classifier_error
        self.generation_error = generation_error
        self.classifier_calls = 0
        self.generation_calls = 0

    def complete(self, system: str, user: str, max_tokens: int = 1000) -> str:
        if system == CLASSIFIER_PROMPT:
            self.classifier_calls += 1
            if self.classifier_error:
                raise RuntimeError("llm down")
            return json.dumps({"label": self.label})
        if system == GENERATION_PROMPT:
            self.generation_calls += 1
            if self.generation_error:
                raise RuntimeError("llm down")
            return self.generations.pop(0)
        raise AssertionError("unexpected prompt")


class SequenceVerifier:
    def __init__(self, verdicts=None):
        self.verdicts = list(verdicts or [])
        self.calls = 0

    def verify(self, claims, sources):
        self.calls += 1
        ok = self.verdicts.pop(0) if self.verdicts else True
        return [ok] * len(claims)


def make(llm, verifier=None):
    index = DocumentIndex(HashEmbedder())
    doc = uuid4()
    index.index_document(doc, ingest_contract(doc, "a.txt", SAMPLE.encode()))
    store = InMemoryEscalationStore()
    pipe = ConversationalPipeline(
        index, llm, verifier or SequenceVerifier(), store, threshold=0.3
    )
    return pipe, doc, store


def ask(pipe, doc, question):
    return pipe.ask(ChatRequest(document_id=doc, question=question))


def test_happy_path_answers_with_citation():
    llm = RouterLLM(generations=[GOOD])
    pipe, doc, _ = make(llm)
    result = ask(pipe, doc, "What is the term of this agreement?")
    r = result.response
    assert r.status == TurnStatus.ANSWERED
    assert r.answer == "The term is five years."
    assert r.citations[0].clause_number == "1.1"
    assert 0.0 <= r.retrieval_score <= 1.0
    assert result.stage == "answered" and result.attempts == 1


def test_advice_rule_escalates_without_calling_llm():
    llm = RouterLLM()
    pipe, doc, store = make(llm)
    result = ask(pipe, doc, "Should I sue them?")
    assert result.response.status == TurnStatus.ESCALATED
    assert result.classifier_source == "rule"
    assert llm.classifier_calls == 0 and llm.generation_calls == 0
    assert len(store.records) == 1


def test_advice_from_llm_escalates_and_never_generates():
    llm = RouterLLM(label="advise")
    pipe, doc, store = make(llm)
    result = ask(pipe, doc, "Would a judge bother with clause two?")
    assert result.response.status == TurnStatus.ESCALATED
    assert result.classifier_source == "llm"
    assert llm.generation_calls == 0
    assert len(store.records) == 1


def test_off_topic_is_refused():
    llm = RouterLLM(label="off_topic")
    pipe, doc, store = make(llm)
    result = ask(pipe, doc, "Who won the cricket match?")
    assert result.response.status == TurnStatus.REFUSED
    assert result.response.reason == ReasonCode.OUT_OF_SCOPE
    assert llm.generation_calls == 0 and store.records == []


def test_classifier_outage_is_not_escalated_to_lawyer():
    llm = RouterLLM(classifier_error=True)
    pipe, doc, store = make(llm)
    result = ask(pipe, doc, "What is the term of this agreement?")
    assert result.response.status == TurnStatus.REFUSED
    assert result.response.reason == ReasonCode.TEMPORARILY_UNAVAILABLE
    assert result.stage == "classifier_unavailable"
    assert store.records == []


def test_low_retrieval_score_skips_generation():
    llm = RouterLLM()
    pipe, doc, _ = make(llm)
    result = ask(pipe, doc, "zebra giraffe quantum")
    assert result.response.reason == ReasonCode.LOW_RETRIEVAL_SCORE
    assert result.stage == "retrieval_gate"
    assert llm.generation_calls == 0


def test_model_says_not_answerable_is_refused_without_retry():
    llm = RouterLLM(generations=[NOT_ANSWERABLE])
    pipe, doc, _ = make(llm)
    result = ask(pipe, doc, "What is the term of this agreement?")
    assert result.response.status == TurnStatus.REFUSED
    assert result.stage == "not_answerable"
    assert llm.generation_calls == 1


def test_verification_fails_twice_is_refused():
    llm = RouterLLM(generations=[GOOD, GOOD])
    verifier = SequenceVerifier([False, False])
    pipe, doc, _ = make(llm, verifier)
    result = ask(pipe, doc, "What is the term of this agreement?")
    assert result.response.status == TurnStatus.REFUSED
    assert result.response.reason == ReasonCode.UNSUPPORTED_BY_SOURCE
    assert result.response.citations == []
    assert result.attempts == 2 and llm.generation_calls == 2


def test_verification_fails_once_then_passes():
    llm = RouterLLM(generations=[GOOD, GOOD])
    verifier = SequenceVerifier([False, True])
    pipe, doc, _ = make(llm, verifier)
    result = ask(pipe, doc, "What is the term of this agreement?")
    assert result.response.status == TurnStatus.ANSWERED
    assert result.attempts == 2


def test_unknown_document_is_not_ready():
    pipe, _, _ = make(RouterLLM())
    result = ask(pipe, uuid4(), "What is the term of this agreement?")
    assert result.response.reason == ReasonCode.DOCUMENT_NOT_READY
    assert result.stage == "document_missing"


def test_generation_error_never_raises():
    llm = RouterLLM(generation_error=True)
    pipe, doc, _ = make(llm)
    result = ask(pipe, doc, "What is the term of this agreement?")
    assert result.response.status == TurnStatus.REFUSED
    assert result.response.reason == ReasonCode.TEMPORARILY_UNAVAILABLE
    assert result.stage == "error"