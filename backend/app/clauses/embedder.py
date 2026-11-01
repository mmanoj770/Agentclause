"""
D3: Embedding pipeline for the clause corpus (Gemini, 768 dims, free tier).

Idempotency rules (lead's requirement):
- A clause is SKIPPED when it already has an embedding made by the current model,
  for its current version, from its current text (title + content hash).
- It is (re-)EMBEDDED when it is new, its text changed, its version changed, or the
  embedding model changed. The reason is logged for every clause.
- Embeddings are a column on the clause row, so re-running never creates duplicates.
- One failing clause does not abort the run: it is reported and the rest continue,
  each clause written inside its own savepoint.
- Clauses are embedded as RETRIEVAL_DOCUMENT; search queries (D4) use RETRIEVAL_QUERY.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass, field

from app.config import settings
from app.gemini import GeminiError, embed_text

EMBEDDING_DIM = 768  # must match vector(768) in migration 12


def to_pgvector(values: list[float]) -> str:
    """Format a vector as a pgvector literal, e.g. '[0.1,0.2]'. Use with %s::vector."""
    return "[" + ",".join(repr(float(v)) for v in values) + "]"


def text_hash(title: str, content: str) -> str:
    """Fingerprint of exactly the text that gets embedded."""
    return hashlib.sha256(f"{title}\n{content}".encode("utf-8")).hexdigest()


def current_model() -> str:
    return settings.gemini_embedding_model


def get_embedding(text: str, title: str | None = None) -> list[float]:
    """Embedding for a clause being stored in the corpus."""
    return embed_text(text, task="RETRIEVAL_DOCUMENT", dim=EMBEDDING_DIM, title=title)


def get_query_embedding(text: str) -> list[float]:
    """Embedding for a search query (used by D4 retrieval)."""
    return embed_text(text, task="RETRIEVAL_QUERY", dim=EMBEDDING_DIM)


def embed_reason(row: dict, model: str) -> str | None:
    """Why this clause needs embedding, or None if it is up to date."""
    if row["embedded_text_hash"] is None:
        return "new"
    if row["embedding_model"] != model:
        return "model changed"
    if row["embedded_version"] != row["version"]:
        return "version changed"
    if row["embedded_text_hash"] != text_hash(row["title"], row["content"]):
        return "text changed"
    if not row["has_embedding"]:
        return "embedding missing"
    return None


def embed_clause(conn, clause_id: str) -> None:
    """Fetch one clause by ID, embed its title + content, write the vector and its tracking data."""
    row = conn.execute(
        "SELECT clause_id, title, content, version FROM clauses WHERE clause_id = %s",
        (clause_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"Clause {clause_id} not found")

    vector = get_embedding(row["content"], title=row["title"])
    if len(vector) != EMBEDDING_DIM:
        raise ValueError(f"Embedding has {len(vector)} dims, expected {EMBEDDING_DIM}")
    conn.execute(
        """
        UPDATE clauses
           SET embedding = %s::vector,
               embedding_model = %s,
               embedded_version = %s,
               embedded_text_hash = %s
         WHERE clause_id = %s
        """,
        (to_pgvector(vector), current_model(), row["version"],
         text_hash(row["title"], row["content"]), row["clause_id"]),
    )


@dataclass
class EmbedRunResult:
    embedded: int = 0
    skipped: int = 0
    failed: list[tuple[str, str]] = field(default_factory=list)  # (clause_id, reason)
    reasons: Counter = field(default_factory=Counter)             # why clauses were embedded

    def summary(self) -> str:
        why = ", ".join(f"{k}: {v}" for k, v in sorted(self.reasons.items())) or "none"
        return (f"embedded {self.embedded} ({why}), skipped {self.skipped} unchanged, "
                f"failed {len(self.failed)}")


def embed_all_pending(conn) -> EmbedRunResult:
    """Embed every clause (staging and verified) that is new or out of date."""
    model = current_model()
    rows = conn.execute(
        """
        SELECT clause_id, title, content, version,
               embedding IS NOT NULL AS has_embedding,
               embedding_model, embedded_version, embedded_text_hash
          FROM clauses
         ORDER BY created_at, clause_id
        """
    ).fetchall()

    result = EmbedRunResult()
    todo = [(row, embed_reason(row, model)) for row in rows]
    pending = [(row, reason) for row, reason in todo if reason is not None]
    result.skipped = len(todo) - len(pending)
    print(f"  {len(rows)} clause(s) found; {len(pending)} to embed with {model}, "
          f"{result.skipped} already up to date.")

    for i, (row, reason) in enumerate(pending, 1):
        clause_id = str(row["clause_id"])
        try:
            with conn.transaction():
                embed_clause(conn, clause_id)
        except (GeminiError, ValueError) as exc:
            result.failed.append((clause_id, str(exc)))
            print(f"  [{i}/{len(pending)}] FAILED {clause_id} ({reason}): {exc}")
            continue
        result.embedded += 1
        result.reasons[reason] += 1
        print(f"  [{i}/{len(pending)}] Embedded {clause_id} ({reason})")

    return result
