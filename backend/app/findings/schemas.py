from typing import Literal

from pydantic import BaseModel, Field

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
