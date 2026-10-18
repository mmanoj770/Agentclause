from typing import Literal

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

Severity = Literal["low", "medium", "high", "critical"]


class FindingIn(BaseModel):
    """The fixed finding schema every pipeline layer must emit. No free-text findings."""
    layer: int = Field(ge=0, le=6)
    severity: Severity
    clause_reference: str | None = None
    description: str = Field(min_length=1)
    rule_applied: str | None = None
    remedy_suggested: str | None = None


class LawyerFindingIn(BaseModel):
    severity: Severity
    description: str = Field(min_length=1)
    clause_reference: str | None = None
    rule_applied: str | None = None
    remedy_suggested: str | None = None
    notes: str | None = None


class AdjudicateIn(BaseModel):
    action: Literal["confirm", "override"]
    notes: str | None = None


class ClientFindingOut(BaseModel):
    """What a startup user may see of a finding, only after lawyer sign-off.

    An allowlist: `layer`, `rule_applied`, `advocate_notes` and who adjudicated are not fields here, so
    they cannot reach the response even if a row carries them. `origin` is derived from the lawyer's
    action ('add' = lawyer-added), never read from the row's content.
    """
    model_config = ConfigDict(extra="forbid")

    finding_id: UUID
    severity: Severity
    clause_reference: str | None = None
    description: str
    remedy_suggested: str | None = None
    citation: str | None = None
    citation_type: str | None = None
    status: Literal["confirmed", "added"]
    origin: Literal["agent", "advocate"]
