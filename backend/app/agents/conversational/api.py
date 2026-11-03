import os
import threading
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, Field, ValidationError

from app.agents.conversational.chat_service import ChatService, ChatUser
from app.agents.conversational.contract import ChatRequest, ChatResponse
from app.agents.conversational.llm import get_llm_client
from app.agents.conversational.retrieval import DocumentIndex
from app.agents.conversational.supabase_adapters import (
    SupabaseChatLog,
    SupabaseDocumentSource,
)
from app.agents.conversational.verification import LLMVerifier, NLIVerifier
from app.audit import write_audit
from app.documents.service import get_document
from app.storage.s3 import get_object_bytes, get_s3


class ChatBody(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    language: Literal["en"] = "en"


class _Lazy:
    def __init__(self, factory):
        self._factory = factory
        self._obj = None
        self._lock = threading.Lock()

    def _get(self):
        with self._lock:
            if self._obj is None:
                self._obj = self._factory()
            return self._obj


class LazyLLM(_Lazy):
    def complete(self, system: str, user: str, max_tokens: int = 1000) -> str:
        return self._get().complete(system, user, max_tokens)


class LazyEmbedder(_Lazy):
    def embed(self, texts):
        return self._get().embed(texts)


class LazyVerifier(_Lazy):
    def verify(self, claims, sources):
        return self._get().verify(claims, sources)


def _sentence_transformer_embedder():
    from app.agents.conversational.embeddings import SentenceTransformerEmbedder

    return SentenceTransformerEmbedder()


_service: ChatService | None = None
_service_lock = threading.Lock()


def get_chat_service() -> ChatService:
    global _service
    with _service_lock:
        if _service is None:
            llm = LazyLLM(get_llm_client)
            if os.environ.get("CHAT_VERIFIER", "nli").lower() == "llm":
                verifier = LazyVerifier(lambda: LLMVerifier(llm))
            else:
                verifier = LazyVerifier(NLIVerifier)
            index = DocumentIndex(LazyEmbedder(_sentence_transformer_embedder))
            _service = ChatService(None, None, index, llm, verifier)
        return _service


def chat_for_document(service: ChatService, conn, user, doc_id, body: ChatBody) -> ChatResponse:
    try:
        request = ChatRequest(document_id=doc_id, question=body.question, language=body.language)
    except ValidationError:
        raise HTTPException(status_code=422, detail="Please enter a question.")

    chat_user = ChatUser(id=str(user.id), role=str(getattr(user.role, "value", user.role)))
    source = SupabaseDocumentSource(conn, user, get_document, get_object_bytes, get_s3)
    chat_log = SupabaseChatLog(conn, write_audit)
    return service.answer(
        chat_user, doc_id, request.question, source=source, chat_log=chat_log
    )
