import logging

from pydantic import BaseModel

from app.agents.conversational.classifier import QuestionLabel, classify
from app.agents.conversational.contract import (
    ChatRequest,
    ChatResponse,
    ReasonCode,
    TurnStatus,
)
from app.agents.conversational.gates import clamp_score, retrieval_gate
from app.agents.conversational.generation import generate_answer
from app.agents.conversational.llm import LLMClient
from app.agents.conversational.retrieval import DocumentIndex
from app.agents.conversational.templates import (
    EscalationStore,
    build_escalation,
    build_refusal,
)
from app.agents.conversational.verification import Verifier, verify_answer

log = logging.getLogger(__name__)


class PipelineResult(BaseModel):
    response: ChatResponse
    stage: str
    classifier_source: str | None = None
    attempts: int = 0


class ConversationalPipeline:
    def __init__(
        self,
        index: DocumentIndex,
        llm: LLMClient,
        verifier: Verifier,
        escalations: EscalationStore,
        threshold: float | None = None,
        top_k: int = 4,
        max_attempts: int = 2,
    ):
        self.index = index
        self.llm = llm
        self.verifier = verifier
        self.escalations = escalations
        self.threshold = threshold
        self.top_k = top_k
        self.max_attempts = max_attempts

    def ask(self, request: ChatRequest) -> PipelineResult:
        try:
            return self._run(request)
        except Exception:
            log.exception("pipeline error")
            return PipelineResult(
                response=build_refusal(request.document_id, ReasonCode.TEMPORARILY_UNAVAILABLE),
                stage="error",
            )

    def _run(self, request: ChatRequest) -> PipelineResult:
        doc = request.document_id
        question = request.question

        if not self.index.has_document(doc):
            return PipelineResult(
                response=build_refusal(doc, ReasonCode.DOCUMENT_NOT_READY),
                stage="document_missing",
            )

        decision = classify(question, self.llm)
        source = decision.source

        if source == "fallback":
            return PipelineResult(
                response=build_refusal(doc, ReasonCode.TEMPORARILY_UNAVAILABLE),
                stage="classifier_unavailable",
                classifier_source=source,
            )
        if decision.label == QuestionLabel.ADVISE:
            return PipelineResult(
                response=build_escalation(doc, question, self.escalations),
                stage="escalated",
                classifier_source=source,
            )
        if decision.label == QuestionLabel.OFF_TOPIC:
            return PipelineResult(
                response=build_refusal(doc, ReasonCode.OUT_OF_SCOPE),
                stage="off_topic",
                classifier_source=source,
            )

        retrieved = self.index.search(doc, question, k=self.top_k)
        gate = retrieval_gate(retrieved, self.threshold)
        if not gate.passed:
            return PipelineResult(
                response=build_refusal(doc, ReasonCode.LOW_RETRIEVAL_SCORE, gate.top_score),
                stage="retrieval_gate",
                classifier_source=source,
            )

        for attempt in range(1, self.max_attempts + 1):
            generated = generate_answer(question, retrieved, self.llm)
            if generated is None:
                return PipelineResult(
                    response=build_refusal(doc, ReasonCode.LOW_RETRIEVAL_SCORE, gate.top_score),
                    stage="not_answerable",
                    classifier_source=source,
                    attempts=attempt,
                )
            check = verify_answer(generated, retrieved, self.verifier)
            if check.passed:
                response = ChatResponse(
                    document_id=doc,
                    status=TurnStatus.ANSWERED,
                    answer=generated.text,
                    citations=generated.citations,
                    retrieval_score=clamp_score(gate.top_score or 0.0),
                )
                return PipelineResult(
                    response=response,
                    stage="answered",
                    classifier_source=source,
                    attempts=attempt,
                )

        return PipelineResult(
            response=build_refusal(doc, ReasonCode.UNSUPPORTED_BY_SOURCE, gate.top_score),
            stage="verification_failed",
            classifier_source=source,
            attempts=self.max_attempts,
        )