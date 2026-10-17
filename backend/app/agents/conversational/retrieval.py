from uuid import UUID

import numpy as np
from pydantic import BaseModel

from app.agents.conversational.contract import CitationSource
from app.agents.conversational.embeddings import Embedder
from app.agents.conversational.ingest import ClauseChunk


class RetrievedChunk(BaseModel):
    chunk: ClauseChunk
    score: float


def embedding_text(chunk: ClauseChunk) -> str:
    return " ".join(part for part in (chunk.heading, chunk.text) if part)


class DocumentIndex:
    def __init__(self, embedder: Embedder):
        self.embedder = embedder
        self._chunks: dict[UUID, list[ClauseChunk]] = {}
        self._vectors: dict[UUID, np.ndarray] = {}

    def index_document(
        self,
        document_id: UUID,
        chunks: list[ClauseChunk],
        notes: list[str] | None = None,
    ) -> None:
        all_chunks = list(chunks)
        for i, note in enumerate(notes or []):
            all_chunks.append(
                ClauseChunk(
                    chunk_id=f"{document_id}:note:{i}",
                    document_id=document_id,
                    source=CitationSource.LAWYER_NOTE,
                    position=len(all_chunks),
                    clause_number=None,
                    heading="Lawyer note",
                    text=note,
                )
            )
        if not all_chunks:
            raise ValueError("nothing to index")
        if any(c.document_id != document_id for c in all_chunks):
            raise ValueError("chunk belongs to a different document")

        self._chunks[document_id] = all_chunks
        self._vectors[document_id] = self.embedder.embed(
            [embedding_text(c) for c in all_chunks]
        )

    def search(self, document_id: UUID, query: str, k: int = 4) -> list[RetrievedChunk]:
        chunks = self._chunks.get(document_id)
        if not chunks:
            return []
        query_vector = self.embedder.embed([query])[0]
        scores = self._vectors[document_id] @ query_vector
        top = np.argsort(-scores)[:k]
        return [RetrievedChunk(chunk=chunks[i], score=float(scores[i])) for i in top]

    def has_document(self, document_id: UUID) -> bool:
        return document_id in self._chunks