import logging
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel

from app.agents.conversational.contract import ChatRequest, ChatResponse, ReasonCode
from app.agents.conversational.ingest import ingest_contract
from app.agents.conversational.llm import LLMClient
from app.agents.conversational.pipeline import ConversationalPipeline, PipelineResult
from app.agents.conversational.retrieval import DocumentIndex
from app.agents.conversational.templates import build_refusal
from app.agents.conversational.verification import Verifier

log = logging.getLogger(__name__)

CHAT_OPEN_STATES = frozenset({"lawyer_approved", "delivered"})
READABLE_SUFFIXES = frozenset({".pdf", ".docx", ".txt"})


class ChatUser(BaseModel):
    id: UUID
    role: str


class DocumentInfo(BaseModel):
    document_id: UUID
    state: str
    version_id: str
    storage_key: str
    filename: str | None = None


class TurnRecord(BaseModel):
    turn_id: UUID
    document_id: UUID
    document_version_id: str | None
    asked_by: UUID
    question: str
    answer: str
    status: str
    reason: str | None
    stage: str
    classifier_source: str | None
    attempts: int
    retrieval_score: float | None
    citations: list[dict]
    escalation_id: UUID | None
    latency_ms: int


class DocumentSource(Protocol):
    def load_document(self, document_id: UUID, user: ChatUser) -> DocumentInfo: ...
    def read_file(self, storage_key: str) -> bytes: ...


class ChatLog(Protocol):
    def save_escalation(self, document_id: UUID, question: str, asked_by: UUID) -> UUID: ...
    def save_turn(self, record: TurnRecord) -> None: ...
    def write_audit(self, document_id: UUID, user: ChatUser, action: str, details: dict) -> None: ...


class UnreadableDocument(Exception):
    pass


class _BoundEscalations:
    def __init__(self, chat_log: ChatLog, asked_by: UUID):
        self.chat_log = chat_log
        self.asked_by = asked_by

    def create(self, document_id: UUID, question: str) -> UUID:
        return self.chat_log.save_escalation(document_id, question, self.asked_by)


class ChatService:
    def __init__(
        self,
        source: DocumentSource,
        chat_log: ChatLog,
        index: DocumentIndex,
        llm: LLMClient,
        verifier: Verifier,
        threshold: float | None = None,
        max_documents: int = 32,
    ):
        self.source = source
        self.log = chat_log
        self.index = index
        self.llm = llm
        self.verifier = verifier
        self.threshold = threshold
        self.max_documents = max_documents
        self._versions: OrderedDict[UUID, str] = OrderedDict()
        self._locks: dict[UUID, threading.Lock] = {}
        self._guard = threading.Lock()

    def answer(self, user: ChatUser, document_id: UUID, question: str) -> ChatResponse:
        started = time.monotonic()
        request = ChatRequest(document_id=document_id, question=question)
        info = self.source.load_document(document_id, user)
        result = self._run(user, request, info)
        self._record(user, info, request, result, started)
        return result.response

    def _run(self, user: ChatUser, request: ChatRequest, info: DocumentInfo) -> PipelineResult:
        if info.state not in CHAT_OPEN_STATES:
            return self._refusal(request, ReasonCode.DOCUMENT_NOT_READY, "state_closed")
        try:
            self._ensure_indexed(info)
        except UnreadableDocument:
            return self._refusal(request, ReasonCode.DOCUMENT_UNREADABLE, "unreadable")
        except Exception:
            log.exception("could not prepare document for chat")
            return self._refusal(request, ReasonCode.TEMPORARILY_UNAVAILABLE, "index_error")

        pipeline = ConversationalPipeline(
            self.index,
            self.llm,
            self.verifier,
            _BoundEscalations(self.log, user.id),
            threshold=self.threshold,
        )
        return pipeline.ask(request)

    @staticmethod
    def _refusal(request: ChatRequest, reason: ReasonCode, stage: str) -> PipelineResult:
        return PipelineResult(
            response=build_refusal(request.document_id, reason), stage=stage
        )

    def _doc_lock(self, document_id: UUID) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(document_id, threading.Lock())

    def _ensure_indexed(self, info: DocumentInfo) -> None:
        with self._doc_lock(info.document_id):
            with self._guard:
                if self._versions.get(info.document_id) == info.version_id:
                    self._versions.move_to_end(info.document_id)
                    return

            name = info.filename or info.storage_key
            if Path(name).suffix.lower() not in READABLE_SUFFIXES:
                raise UnreadableDocument(name)

            data = self.source.read_file(info.storage_key)
            try:
                chunks = ingest_contract(info.document_id, name, data)
            except ValueError as exc:
                raise UnreadableDocument(str(exc)) from exc
            self.index.index_document(info.document_id, chunks)

            with self._guard:
                self._versions[info.document_id] = info.version_id
                self._versions.move_to_end(info.document_id)
                evicted = []
                while len(self._versions) > self.max_documents:
                    oldest, _ = self._versions.popitem(last=False)
                    evicted.append(oldest)
            for old in evicted:
                self.index.remove_document(old)

    def _record(
        self,
        user: ChatUser,
        info: DocumentInfo,
        request: ChatRequest,
        result: PipelineResult,
        started: float,
    ) -> None:
        r = result.response
        record = TurnRecord(
            turn_id=r.turn_id,
            document_id=r.document_id,
            document_version_id=info.version_id,
            asked_by=user.id,
            question=request.question,
            answer=r.answer,
            status=r.status.value,
            reason=r.reason.value if r.reason else None,
            stage=result.stage,
            classifier_source=result.classifier_source,
            attempts=result.attempts,
            retrieval_score=r.retrieval_score,
            citations=[c.model_dump(mode="json") for c in r.citations],
            escalation_id=r.escalation_id,
            latency_ms=int((time.monotonic() - started) * 1000),
        )
        try:
            self.log.save_turn(record)
        except Exception:
            log.exception("could not save chat turn")
        try:
            self.log.write_audit(
                r.document_id,
                user,
                "chat_turn",
                {
                    "turn_id": str(r.turn_id),
                    "question_length": len(request.question),
                    "status": r.status.value,
                    "stage": result.stage,
                },
            )
        except Exception:
            log.exception("could not write chat audit entry")