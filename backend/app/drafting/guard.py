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

Lawyer-facing output REQUIRES `conn`: each clause is re-checked in the database at
render time. A clause blocks the draft if it is no longer verified, no longer exists,
has a different version, or its approved text has changed since the draft was made
(a "verified" label only vouches for the text the lawyer verified). If the check
cannot run or fails, lawyer output is refused (fail closed).

`complete` is False when the draft still contains unfilled placeholders such as
[City] or unresolved cross-references, even if it is allowed to be shown.
"""

from __future__ import annotations

import hashlib
import re
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
    complete: bool = True  # False while placeholders or unresolved references remain in the text
    issues: list[str] = Field(default_factory=list)  # things a reviewer should look at


def _db_state(conn, clause_ids: list[UUID]) -> dict[UUID, dict]:
    """Current status, version and text fingerprint of each clause, straight from the database."""
    # Savepoint: if this query fails, the caller's connection stays usable.
    with conn.transaction():
        rows = conn.execute(
            "SELECT clause_id, verification_status::text AS status, version, content FROM clauses "
            "WHERE clause_id = ANY(%s::uuid[])",
            ([str(i) for i in clause_ids],),
        ).fetchall()
    return {
        UUID(str(r["clause_id"])): {
            "status": r["status"],
            "version": r["version"],
            "sha256": hashlib.sha256(r["content"].encode("utf-8")).hexdigest(),
        }
        for r in rows
    }


PLACEHOLDER_LEFT_RE = re.compile(r"\[[^\[\]\n]{1,60}\]|UNRESOLVED REFERENCE")


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

    # What each clause looks like right now in the database (None = could not check).
    live: dict[UUID, dict] | None = None
    db_check_failed = False
    if conn is not None and draft.clauses:
        try:
            live = _db_state(conn, [c.clause_id for c in draft.clauses])
        except Exception as exc:  # any DB failure must fail closed, never crash
            db_check_failed = True
            issues.append(f"Could not re-check clauses in the database: {type(exc).__name__}")
    no_live_check = conn is None

    blocked: list[BlockedClause] = []
    for c in draft.clauses:
        if live is None:
            status, reason = str(c.verification_status), None  # trust the draft only for internal use
        else:
            now = live.get(c.clause_id)
            if now is None:
                status, reason = "missing", "clause no longer exists in the corpus"
            elif now["status"] != VerificationStatus.verified:
                status, reason = now["status"], f"clause is '{now['status']}', not verified"
            elif c.version != now["version"]:
                status, reason = "changed", (f"clause was updated from version {c.version} to "
                                             f"{now['version']} after this draft was made")
            elif c.source_sha256 and c.source_sha256 != now["sha256"]:
                status, reason = "changed", "the approved clause text changed after this draft was made"
            else:
                status, reason = "verified", None
        if status == VerificationStatus.verified:
            continue
        blocked.append(BlockedClause(number=c.number, clause_id=c.clause_id, clause_type=c.clause_type,
                                     reason=reason or f"clause is '{status}', not verified"))

    if audience == Audience.lawyer:
        if not draft.clauses:
            issues.append("Draft has no clauses.")
        if no_live_check:
            issues.append("Lawyer-facing output requires a live database check (pass conn).")
        if blocked or db_check_failed or no_live_check or not draft.clauses:
            return GuardResult(audience=audience, allowed=False, text=None,
                               blocked=blocked, complete=False, issues=issues)
        text = _render_text(draft, draft_label_for=set(), banner=None, label=DRAFT_LABEL)
        return _finish(audience, True, text, blocked, issues)

    # Internal view: always rendered, unverified content clearly labelled.
    unverified = {b.clause_id for b in blocked}
    if db_check_failed:
        unverified = {c.clause_id for c in draft.clauses}
    banner = DRAFT_BANNER if unverified else None
    text = _render_text(draft, draft_label_for=unverified, banner=banner, label=DRAFT_LABEL)
    return _finish(audience, True, text, blocked, issues)


def _finish(audience, allowed, text, blocked, issues) -> GuardResult:
    left = sorted(set(PLACEHOLDER_LEFT_RE.findall(text)))
    if left:
        issues = issues + [f"Draft is incomplete: {', '.join(left)} still in the text."]
    return GuardResult(audience=audience, allowed=allowed, text=text, blocked=blocked,
                       complete=not left, issues=issues)
