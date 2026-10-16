"""
D3: Embedding pipeline using Google Gemini text-embedding-004 (768 dims, free tier).

Key design decisions:
- embed_all_pending() only processes clauses with embedding IS NULL → idempotent
- Re-running is safe: already-embedded clauses are skipped automatically
- When moving to a paid model later, only get_embedding() needs to change
"""

import httpx

from app.config import settings

GEMINI_EMBEDDING_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "text-embedding-004:embedContent"
)


def get_embedding(text: str) -> list[float]:
    """
    Call Gemini text-embedding-004 and return a 768-dim vector.
    Raises httpx.HTTPStatusError on API failure.
    """
    if not settings.gemini_api_key:
        raise ValueError(
            "GEMINI_API_KEY is not set. Add it to your .env.local file."
        )

    response = httpx.post(
        GEMINI_EMBEDDING_URL,
        params={"key": settings.gemini_api_key},
        json={
            "model": "models/text-embedding-004",
            "content": {"parts": [{"text": text}]},
        },
        timeout=30,
    )
    response.raise_for_status()
    return response.json()["embedding"]["values"]


def embed_clause(conn, clause_id: str) -> None:
    """Fetch one clause by ID, embed its content, write the vector back."""
    row = conn.execute(
        "SELECT clause_id, content FROM clauses WHERE clause_id = %s",
        (clause_id,),
    ).fetchone()

    if row is None:
        raise ValueError(f"Clause {clause_id} not found")

    vector = get_embedding(row["content"])

    conn.execute(
        "UPDATE clauses SET embedding = %s WHERE clause_id = %s",
        (vector, str(row["clause_id"])),
    )


def embed_all_pending(conn) -> int:
    """
    Embed every clause that has no embedding yet.
    Idempotent: skips clauses that already have one.
    Returns count of clauses embedded this run.
    """
    rows = conn.execute(
        "SELECT clause_id FROM clauses WHERE embedding IS NULL"
    ).fetchall()

    total = len(rows)
    if total == 0:
        print("  All clauses already embedded — nothing to do.")
        return 0

    for i, row in enumerate(rows, 1):
        embed_clause(conn, str(row["clause_id"]))
        print(f"  [{i}/{total}] Embedded clause {row['clause_id']}")

    return total
