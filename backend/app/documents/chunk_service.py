"""
document_chunks access (migration 19).

document_chunks has RLS on and no client grants, so every read goes through
get_chunks_for_version, which enforces the same visibility as documents.service:
a startup user sees their own org's documents, a lawyer sees only documents
assigned to them. Chunks are always fetched for ONE version of ONE document;
there is no cross-document query here.
"""

from dataclasses import dataclass

from fastapi import HTTPException

from app.auth.dependencies import CurrentUser
from app.clauses.embedder import current_model, text_hash, to_pgvector
from app.documents.service import Actor, _can_view
from app.documents.states import DocState

# Document states in which the conversational agent may read a version's chunks:
# once AI review has finished. Not during drafting or while review is still writing them.
CHAT_STATES = frozenset(DocState) - {DocState.DRAFTED, DocState.UNDER_AI_REVIEW}


@dataclass
class Chunk:
    text: str
    clause_number: str | None = None
    heading: str | None = None
    embedding: list[float] | None = None


def get_chunks_for_version(conn, user: CurrentUser, document_id, document_version_id) -> list[dict]:
    actor = Actor.from_user(user)
    doc = conn.execute("select * from documents where id = %s", (document_id,)).fetchone()
    # Same answer for "doesn't exist", "not yours" and "wrong version": no leaking.
    if doc is None or not _can_view(doc, actor):
        raise HTTPException(404, "Document not found")
    version = conn.execute(
        "select id from document_versions where id = %s and document_id = %s",
        (document_version_id, document_id),
    ).fetchone()
    if version is None:
        raise HTTPException(404, "Document not found")
    if doc["state"] not in CHAT_STATES:
        raise HTTPException(409, f"Chat is not available while the document is '{doc['state']}'")
    return conn.execute(
        """select id, chunk_index, clause_number, heading, text, embedding_model
           from document_chunks
           where document_id = %s and document_version_id = %s
           order by chunk_index""",
        (document_id, document_version_id),
    ).fetchall()


def create_chunks(conn, document_version_id, chunks: list[Chunk]) -> int:
    """Replace a version's chunks. Backend only: called by intake after chunking/embedding."""
    with conn.transaction():
        version = conn.execute(
            "select document_id, version_no from document_versions where id = %s",
            (document_version_id,),
        ).fetchone()
        if version is None:
            raise ValueError(f"Unknown document version {document_version_id}")
        conn.execute("delete from document_chunks where document_version_id = %s", (document_version_id,))
        rows = [c for c in chunks if c.text.strip()]
        for i, c in enumerate(rows):
            embedded = c.embedding is not None
            conn.execute(
                """insert into document_chunks
                     (document_id, document_version_id, chunk_index, clause_number, heading, text,
                      embedding, embedding_model, embedded_version, embedded_text_hash)
                   values (%s, %s, %s, %s, %s, %s, %s::vector, %s, %s, %s)""",
                (version["document_id"], document_version_id, i, c.clause_number, c.heading, c.text,
                 to_pgvector(c.embedding) if embedded else None,
                 current_model() if embedded else None,
                 version["version_no"] if embedded else None,
                 text_hash(c.heading or "", c.text) if embedded else None),
            )
    return len(rows)
