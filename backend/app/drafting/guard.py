"""
D8: Verified-only output guard.

The single gate between a draft and anyone reading it.

- Audience.lawyer:   allowed ONLY if every clause is verified. If any clause is
                     staging (or cannot be confirmed), nothing is rendered:
                     allowed=False, text=None, and the blocking clauses are listed.
                     Clauses are never silently dropped, because a contract with
                     a missing clause is worse than no contract.
- Audience.internal: always rendered (for developers / testing), but every
                     unverified clause is labelled DRAFT and the document
                     carries a warning banner.

Pass `conn` to re-check each clause's status in the database at render time
(recommended). This catches a clause that was demoted after retrieval or that
no longer exists. If that check fails, lawyer output is refused (fail closed).
"""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field

from app.clauses.models import VerificationStatus
from app.drafting.adaptation import AdaptationStatus
from app.drafting.assembly import DraftDocument, _render_text

DRAFT_LABEL = "[DRAFT - UNVERIFIED CLAUSE]"
DRAFT_BANNER = (
    "*** DRAFT - CONTAINS UNVERIFIED (STAGING) CLAUSES. "
    "NOT FOR LAWYER OR CLIENT USE. ***"
)


class Audience(StrEnum):
    lawyer = "lawyer"
    internal = "internal"


class BlockedClause(BaseModel):
    number: int
    clause_id: UUID
    clause_type: str
    reason: str


class GuardResult(BaseModel):
    audience: Audience
    allowed: bool
    text: str | None = None
    blocked: list[BlockedClause] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)  # things a reviewer should look at


def _db_statuses(conn, clause_ids: list[UUID]) -> dict[UUID, str]:
    # Savepoint: if this query fails, the caller's connection stays usable.
    with conn.transaction():
        rows = conn.execute(
            "SELECT clause_id, verification_status::text AS status FROM clauses "
            "WHERE clause_id = ANY(%s::uuid[])",
            ([str(i) for i in clause_ids],),
        ).fetchall()
    return {UUID(str(r["clause_id"])): r["status"] for r in rows}


def _review_issues(draft: DraftDocument) -> list[str]:
    issues = list(draft.warnings)
    for c in draft.clauses:
        where = f"Clause {c.number} ({c.clause_type})"
        if c.unresolved_placeholders:
            issues.append(f"{where}: unfilled placeholder(s) {c.unresolved_placeholders}")
        if c.unresolved_citations:
            issues.append(f"{where}: unknown statute code(s) {c.unresolved_citations}")
        if c.adaptation_status == AdaptationStatus.fallback_original:
            issues.append(f"{where}: deal facts were not applied; original approved text used")
        for e in c.edits_applied:
            issues.append(f"{where}: '{e.find}' -> '{e.replace}' (from {e.fact})")
    return issues


def render_for(draft: DraftDocument, audience: Audience | str, *, conn=None) -> GuardResult:
    audience = Audience(audience)
    issues = _review_issues(draft)

    statuses = {c.clause_id: str(c.verification_status) for c in draft.clauses}
    db_check_failed = False
    if conn is not None and draft.clauses:
        try:
            live = _db_statuses(conn, list(statuses))
        except Exception as exc:  # any DB failure must fail closed, never crash
            db_check_failed = True
            issues.append(f"Could not re-check clause status in the database: {type(exc).__name__}")
        else:
            for cid in statuses:
                statuses[cid] = live.get(cid, "missing")

    blocked: list[BlockedClause] = []
    for c in draft.clauses:
        status = statuses[c.clause_id]
        if status == VerificationStatus.verified:
            continue
        reason = ("clause no longer exists in the corpus" if status == "missing"
                  else f"clause is '{status}', not verified")
        blocked.append(BlockedClause(number=c.number, clause_id=c.clause_id,
                                     clause_type=c.clause_type, reason=reason))

    if audience == Audience.lawyer:
        if not draft.clauses:
            issues.append("Draft has no clauses.")
        if blocked or db_check_failed or not draft.clauses:
            return GuardResult(audience=audience, allowed=False, text=None,
                               blocked=blocked, issues=issues)
        text = _render_text(draft, draft_label_for=set(), banner=None, label=DRAFT_LABEL)
        return GuardResult(audience=audience, allowed=True, text=text, issues=issues)

    # Internal view: always rendered, unverified content clearly labelled.
    unverified = {b.clause_id for b in blocked}
    if db_check_failed:
        unverified = {c.clause_id for c in draft.clauses}
    banner = DRAFT_BANNER if unverified else None
    text = _render_text(draft, draft_label_for=unverified, banner=banner, label=DRAFT_LABEL)
    return GuardResult(audience=audience, allowed=True, text=text, blocked=blocked, issues=issues)
