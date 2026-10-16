"""
D3: Embedding pipeline for the clause corpus (Gemini, 768 dims, free tier).

Key design decisions:
- embed_all_pending() only processes clauses with embedding IS NULL -> idempotent.
- Migration 13 resets a clause's embedding to NULL whenever its title or content
  changes, so re-running after a corpus change re-embeds exactly what changed.
- One failing clause does not abort the run: it is reported and the rest continue.
- Clauses are embedded as RETRIEVAL_DOCUMENT; search queries (D4) use
  RETRIEVAL_QUERY. Using the matching task types improves retrieval quality.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.gemini import GeminiError, embed_text

EMBEDDING_DIM = 768  # must match vector(768) in migration 12


def to_pgvector(values: list[float]) -> str:
    """Format a vector as a pgvector literal, e.g. '[0.1,0.2]'. Use with %s::vector."""
    return "[" + ",".join(repr(float(v)) for v in values) + "]"


def get_embedding(text: str, title: str | None = None) -> list[float]:
    """Embedding for a clause being stored in the corpus."""
    return embed_text(text, task="RETRIEVAL_DOCUMENT", dim=EMBEDDING_DIM, title=title)


def get_query_embedding(text: str) -> list[float]:
    """Embedding for a search query (used by D4 retrieval)."""
    return embed_text(text, task="RETRIEVAL_QUERY", dim=EMBEDDING_DIM)


def embed_clause(conn, clause_id: str) -> None:
    """Fetch one clause by ID, embed its title + content, write the vector back."""
    row = conn.execute(
        "SELECT clause_id, title, content FROM clauses WHERE clause_id = %s",
        (clause_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"Clause {clause_id} not found")

    vector = get_embedding(row["content"], title=row["title"])
    conn.execute(
        "UPDATE clauses SET embedding = %s::vector WHERE clause_id = %s",
        (to_pgvector(vector), row["clause_id"]),
    )


@dataclass
class EmbedRunResult:
    embedded: int = 0
    failed: list[tuple[str, str]] = field(default_factory=list)  # (clause_id, reason)


def embed_all_pending(conn) -> EmbedRunResult:
    """
    Embed every clause that has no embedding yet.
    Idempotent: clauses that already have an embedding are skipped.
    Each clause is written inside its own savepoint, so a failure on one clause
    never loses the clauses embedded before it.
    """
    rows = conn.execute(
        "SELECT clause_id FROM clauses WHERE embedding IS NULL ORDER BY created_at, clause_id"
    ).fetchall()

    result = EmbedRunResult()
    total = len(rows)
    if total == 0:
        print("  All clauses already embedded - nothing to do.")
        return result

    for i, row in enumerate(rows, 1):
        clause_id = str(row["clause_id"])
        try:
            with conn.transaction():
                embed_clause(conn, clause_id)
        except (GeminiError, ValueError) as exc:
            result.failed.append((clause_id, str(exc)))
            print(f"  [{i}/{total}] FAILED clause {clause_id}: {exc}")
            continue
        result.embedded += 1
        print(f"  [{i}/{total}] Embedded clause {clause_id}")

    return result
