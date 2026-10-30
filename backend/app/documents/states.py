from enum import StrEnum


class DocState(StrEnum):
    DRAFTED = "drafted"
    UNDER_AI_REVIEW = "under_ai_review"
    PENDING_LAWYER_REVIEW = "pending_lawyer_review"
    LAWYER_COMMENTED = "lawyer_commented"
    REVISION_IN_PROGRESS = "revision_in_progress"
    LAWYER_APPROVED = "lawyer_approved"
    DELIVERED = "delivered"
    NEGOTIATION_IN_PROGRESS = "negotiation_in_progress"  # Path 2, future: no transitions yet


SYSTEM, STARTUP, LAWYER = "system", "startup_user", "lawyer"

# (from_state, to_state) -> who may make this move. Anything not listed is illegal.
TRANSITIONS: dict[tuple[DocState, DocState], frozenset[str]] = {
    (DocState.DRAFTED, DocState.UNDER_AI_REVIEW): frozenset({SYSTEM}),
    (DocState.UNDER_AI_REVIEW, DocState.PENDING_LAWYER_REVIEW): frozenset({SYSTEM}),
    # A failed AI review goes back to the state it started from, so it can be started again (R10).
    (DocState.UNDER_AI_REVIEW, DocState.DRAFTED): frozenset({SYSTEM}),
    (DocState.UNDER_AI_REVIEW, DocState.REVISION_IN_PROGRESS): frozenset({SYSTEM}),
    (DocState.PENDING_LAWYER_REVIEW, DocState.LAWYER_COMMENTED): frozenset({LAWYER}),
    (DocState.PENDING_LAWYER_REVIEW, DocState.LAWYER_APPROVED): frozenset({LAWYER}),
    (DocState.LAWYER_COMMENTED, DocState.REVISION_IN_PROGRESS): frozenset({STARTUP, SYSTEM}),
    (DocState.REVISION_IN_PROGRESS, DocState.UNDER_AI_REVIEW): frozenset({SYSTEM}),
    (DocState.LAWYER_APPROVED, DocState.DELIVERED): frozenset({SYSTEM}),
}
