"""
D4: Retrieval function.

Queries the clause corpus by contract type, clause type and optional filters,
and (when a search query is given) ranks results by cosine similarity using the
pgvector embeddings from D3. Returns the top-k clauses with similarity scores.

Accuracy safeguards
- Exact search: the ivfflat index (lists=10) gives poor recall on a small corpus
  and can silently drop matches when combined with WHERE filters. We set
  ivfflat.probes high enough to scan every list, which makes the search exact.
- Clauses without an embedding cannot be ranked. They are not silently ignored:
  the count is reported in `unembedded_matches` and in `warnings`.
- If the query embedding cannot be created (no API key, network, quota), the
  function falls back to filter-only results and says so in `warnings`
  instead of crashing.
- verified_only=True must be used for anything lawyer-facing (see D8).
"""

from __future__ import annotations

from typing import Callable
from uuid import UUID

from pydantic import BaseModel, Field

from app.clauses.embedder import EMBEDDING_DIM, get_query_embedding, to_pgvector
from app.clauses.models import FavouredParty, VerificationStatus
from app.gemini import GeminiError

MAX_TOP_K = 50
# >= the ivfflat `lists` value in migration 12, so every list is scanned (exact search).
IVFFLAT_PROBES = 100


class RetrievedClause(BaseModel):
    clause_id: UUID
    clause_type: str
    contract_types: list[str]
    favoured_party: FavouredParty
    statute_refs: list[str]
    version: int
    verification_status: VerificationStatus
    title: str
    content: str
    # Cosine similarity (1.0 = identical meaning). None when no search query was given.
    similarity: float | None = None


class RetrievalResult(BaseModel):
    clauses: list[RetrievedClause] = Field(default_factory=list)
    unembedded_matches: int = 0  # matching clauses skipped because they have no embedding
    warnings: list[str] = Field(default_factory=list)


def _clean(value: str | None, name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def retrieve_clauses(
    conn,
    *,
    contract_type: str,
    clause_type: str | None = None,
    query: str | None = None,
    top_k: int = 5,
    verified_only: bool = False,
    favoured_party: str | None = None,
    statute_ref: str | None = None,
    min_similarity: float | None = None,
    embed_query: Callable[[str], list[float]] = get_query_embedding,
) -> RetrievalResult:
    """
    Find clauses for a contract.

    contract_type   required, e.g. "nda" (matches any entry in clauses.contract_types)
    clause_type     optional exact match, e.g. "governing_law"
    query           optional free text; when given, results are ranked by similarity
    top_k           1..50
    verified_only   True for lawyer-facing use: excludes staging clauses
    favoured_party  optional: "party_a" | "party_b" | "neutral"
    statute_ref     optional: only clauses citing this code, e.g. "ICA_s74"
    min_similarity  optional threshold (only with query); weaker matches are dropped

    Raises ValueError for invalid arguments (programmer error); never raises for
    embedding/API problems (falls back and reports in warnings).
    """
    contract_type = _clean(contract_type, "contract_type")
    if contract_type is None:
        raise ValueError("contract_type is required")
    clause_type = _clean(clause_type, "clause_type")
    statute_ref = _clean(statute_ref, "statute_ref")
    if query is not None:
        if not isinstance(query, str):
            raise ValueError("query must be a string")
        query = query.strip() or None
    if isinstance(top_k, bool) or not isinstance(top_k, int) or not 1 <= top_k <= MAX_TOP_K:
        raise ValueError(f"top_k must be an integer between 1 and {MAX_TOP_K}")
    party = FavouredParty(favoured_party).value if favoured_party is not None else None
    if min_similarity is not None:
        if query is None:
            raise ValueError("min_similarity only applies when a query is given")
        if not -1.0 <= float(min_similarity) <= 1.0:
            raise ValueError("min_similarity must be between -1 and 1")

    result = RetrievalResult()
    params = {
        "contract_type": contract_type,
        "clause_type": clause_type,
        "verified_only": bool(verified_only),
        "favoured_party": party,
        "statute_ref": statute_ref,
        "top_k": top_k,
    }
    filters = """
        %(contract_type)s = ANY(contract_types)
        AND (%(clause_type)s::text IS NULL OR clause_type = %(clause_type)s::text)
        AND (NOT %(verified_only)s OR verification_status = 'verified')
        AND (%(favoured_party)s::favoured_party IS NULL
             OR favoured_party = %(favoured_party)s::favoured_party)
        AND (%(statute_ref)s::text IS NULL OR %(statute_ref)s::text = ANY(statute_refs))
    """
    columns = """
        clause_id, clause_type, contract_types, favoured_party::text AS favoured_party,
        statute_refs, version, verification_status::text AS verification_status,
        title, content
    """

    query_vector: str | None = None
    if query is not None:
        try:
            vec = embed_query(query)
            if len(vec) != EMBEDDING_DIM:
                raise GeminiError(f"query embedding has {len(vec)} dims, expected {EMBEDDING_DIM}")
            query_vector = to_pgvector(vec)
        except (GeminiError, ValueError) as exc:
            result.warnings.append(
                f"Semantic ranking unavailable ({exc}); results are filter-only and unranked."
            )

    with conn.transaction():
        if query_vector is not None:
            conn.execute("SELECT set_config('ivfflat.probes', %s, true)", (str(IVFFLAT_PROBES),))
            params["qvec"] = query_vector
            rows = conn.execute(
                f"""
                SELECT {columns},
                       1 - (embedding <=> %(qvec)s::vector) AS similarity
                FROM clauses
                WHERE {filters} AND embedding IS NOT NULL
                ORDER BY embedding <=> %(qvec)s::vector, clause_id
                LIMIT %(top_k)s
                """,
                params,
            ).fetchall()
            missing = conn.execute(
                f"SELECT count(*) AS n FROM clauses WHERE {filters} AND embedding IS NULL",
                params,
            ).fetchone()
            result.unembedded_matches = int(missing["n"])
            if result.unembedded_matches:
                result.warnings.append(
                    f"{result.unembedded_matches} matching clause(s) have no embedding and were "
                    "not ranked. Run: python -m app.clauses.embed_runner"
                )
        else:
            # No ranking possible: verified first, newest version first, stable order.
            rows = conn.execute(
                f"""
                SELECT {columns}, NULL::float8 AS similarity
                FROM clauses
                WHERE {filters}
                ORDER BY (verification_status = 'verified') DESC, version DESC,
                         created_at, clause_id
                LIMIT %(top_k)s
                """,
                params,
            ).fetchall()

    clauses = [RetrievedClause(**row) for row in rows]
    if min_similarity is not None and query_vector is not None:
        clauses = [c for c in clauses if c.similarity is not None and c.similarity >= min_similarity]
    result.clauses = clauses
    if not clauses:
        result.warnings.append("No clauses matched the given filters.")
    return result
