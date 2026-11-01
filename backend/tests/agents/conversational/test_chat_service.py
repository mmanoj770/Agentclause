import json
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.agents.conversational.chat_service import ChatService, ChatUser, DocumentInfo
from app.agents.conversational.classifier import SYSTEM_PROMPT as CLASSIFIER_PROMPT
from app.agents.conversational.contract import ReasonCode, TurnStatus
from app.agents.conversational.embeddings import HashEmbedder
from app.agents.conversational.generation import SYSTEM_PROMPT as GENERATION_PROMPT
from app.agents.conversational.retrieval import DocumentIndex

SAMPLE = """1. Term
1.1 The Term of this agreement is five years from the effective date.

2. Governing Law
2.1 This Agreement is governed by the laws of India.
"""
GOOD = json.dumps(
    {"answerable": True, "claims": [{"text": "The term is five years.", "sources": [1]}]}
)
QUESTION = "What is the term of this agreement?"
USER = ChatUser(id=uuid4(), role="startup_user")


class RouterLLM:
    def __init__(self, generations=None):
        self.generations = list(generations or [])
        self.classifier_calls = 0
        self.generation_calls = 0

    def complete(self, system: str, user: str, max_tokens: int = 1000) -> str:
        if system == CLASSIFIER_PROMPT:
            self.classifier_calls += 1
            return json.dumps({"label": "explain"})
        if system == GENERATION_PROMPT:
            self.generation_calls += 1
            return self.generations.pop(0)
        raise AssertionError("unexpected prompt")


class AlwaysTrue:
    def verify(self, claims, sources):
        return [True] * len(claims)


class FakeSource:
    def __init__(self):
        self.docs = {}
        self.files = {}
        self.reads = 0

    def load_document(self, document_id, user):
        if document_id not in self.docs:
            raise PermissionError("no access")
        return self.docs[document_id]

    def read_file(self, storage_key):
        self.reads += 1
        return self.files[storage_key]


class FakeLog:
    def __init__(self, fail_turn=False):
        self.escalations = []
        self.turns = []
        self.audits = []
        self.fail_turn = fail_turn

    def save_escalation(self, document_id, question, asked_by):
        escalation_id = uuid4()
        self.escalations.append((escalation_id, document_id, question, asked_by))
        return escalation_id

    def save_turn(self, record):
        if self.fail_turn:
            raise RuntimeError("db down")
        self.turns.append(record)

    def write_audit(self, document_id, user, action, details):
        self.audits.append((document_id, user.id, action, details))


def add_doc(source, name="nda.txt", state="lawyer_approved", content=SAMPLE):
    doc = uuid4()
    key = f"org/{doc}/v1/{name}"
    source.docs[doc] = DocumentInfo(
        document_id=doc, state=state, version_id="v1", storage_key=key, filename=name
    )
    source.files[key] = content.encode()
    return doc


def make(generations=None, chat_log=None, max_documents=32):
    source = FakeSource()
    chat_log = chat_log or FakeLog()
    llm = RouterLLM(generations or [GOOD, GOOD])
    service = ChatService(
        source,
        chat_log,
        DocumentIndex(HashEmbedder()),
        llm,
        AlwaysTrue(),
        threshold=0.3,
        max_documents=max_documents,
    )
    return service, source, chat_log, llm


def test_answers_and_caches_index_per_version():
    service, source, chat_log, _ = make()
    doc = add_doc(source)
    first = service.answer(USER, doc, QUESTION)
    second = service.answer(USER, doc, QUESTION)
    assert first.status == TurnStatus.ANSWERED
    assert second.status == TurnStatus.ANSWERED
    assert source.reads == 1
    assert len(chat_log.turns) == 2


def test_closed_state_refused_without_reading_or_llm():
    service, source, chat_log, llm = make()
    doc = add_doc(source, state="pending_lawyer_review")
    response = service.answer(USER, doc, QUESTION)
    assert response.reason == ReasonCode.DOCUMENT_NOT_READY
    assert source.reads == 0 and llm.classifier_calls == 0
    assert chat_log.turns[0].stage == "state_closed"


def test_image_upload_is_unreadable_without_reading_file():
    service, source, chat_log, _ = make()
    doc = add_doc(source, name="scan.png")
    response = service.answer(USER, doc, QUESTION)
    assert response.reason == ReasonCode.DOCUMENT_UNREADABLE
    assert source.reads == 0
    assert chat_log.turns[0].stage == "unreadable"


def test_empty_text_file_is_unreadable():
    service, source, _, _ = make()
    doc = add_doc(source, content="   ")
    response = service.answer(USER, doc, QUESTION)
    assert response.reason == ReasonCode.DOCUMENT_UNREADABLE
    assert source.reads == 1


def test_new_version_triggers_reindex():
    service, source, _, _ = make()
    doc = add_doc(source)
    service.answer(USER, doc, QUESTION)
    old = source.docs[doc]
    key = f"org/{doc}/v2/nda.txt"
    source.docs[doc] = old.model_copy(update={"version_id": "v2", "storage_key": key})
    source.files[key] = SAMPLE.encode()
    service.answer(USER, doc, QUESTION)
    assert source.reads == 2


def test_access_error_propagates_and_nothing_is_logged():
    service, source, chat_log, _ = make()
    add_doc(source)
    with pytest.raises(PermissionError):
        service.answer(USER, uuid4(), QUESTION)
    assert chat_log.turns == [] and chat_log.audits == []


def test_audit_entry_never_contains_question_text():
    service, source, chat_log, _ = make()
    doc = add_doc(source)
    service.answer(USER, doc, QUESTION)
    details = chat_log.audits[0][3]
    assert chat_log.audits[0][2] == "chat_turn"
    assert QUESTION not in str(details)
    assert details["question_length"] == len(QUESTION)
    assert chat_log.turns[0].question == QUESTION


def test_escalation_saved_with_asker_and_linked_to_turn():
    service, source, chat_log, llm = make()
    doc = add_doc(source)
    response = service.answer(USER, doc, "Should I sue them?")
    assert response.status == TurnStatus.ESCALATED
    assert chat_log.escalations[0][3] == USER.id
    assert chat_log.turns[0].escalation_id == response.escalation_id
    assert llm.generation_calls == 0


def test_log_failure_does_not_break_the_answer():
    chat_log = FakeLog(fail_turn=True)
    service, source, _, _ = make(chat_log=chat_log)
    doc = add_doc(source)
    response = service.answer(USER, doc, QUESTION)
    assert response.status == TurnStatus.ANSWERED
    assert len(chat_log.audits) == 1


def test_oldest_document_is_evicted():
    service, source, _, _ = make(max_documents=1)
    first = add_doc(source)
    second = add_doc(source)
    service.answer(USER, first, QUESTION)
    service.answer(USER, second, QUESTION)
    assert not service.index.has_document(first)
    assert service.index.has_document(second)


def test_question_over_1000_characters_rejected():
    service, source, chat_log, _ = make()
    doc = add_doc(source)
    with pytest.raises(ValidationError):
        service.answer(USER, doc, "a" * 1001)
    assert chat_log.turns == []