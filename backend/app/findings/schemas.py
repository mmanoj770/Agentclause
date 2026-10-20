from datetime import date, datetime
from typing import Annotated, Literal, Union
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.schemas.finding import Layer

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


# `finding_id` is the canonical id of a finding. `id` is kept as a deprecated alias so a client that
# still reads `id` keeps working until the integration day. It is removed after this date
# (tests/test_finding_views.py fails once the date has passed, so the alias cannot outlive it).
ID_ALIAS_UNTIL = date(2026, 10, 21)


class _FindingId(BaseModel):
    finding_id: UUID

    @computed_field(description="Deprecated alias of finding_id; removed after ID_ALIAS_UNTIL.")
    @property
    def id(self) -> UUID:
        return self.finding_id


class ClientFindingOut(_FindingId):
    """What a startup user may see of a finding, only after lawyer sign-off.

    An allowlist: `layer`, `rule_applied`, `advocate_notes` and who adjudicated are not fields here, so
    they cannot reach the response even if a row carries them. `origin` is derived from the lawyer's
    action ('add' = lawyer-added), never read from the row's content.
    """
    model_config = ConfigDict(extra="forbid")

    severity: Severity
    clause_reference: str | None = None
    description: str
    remedy_suggested: str | None = None
    citation: str | None = None
    citation_type: str | None = None
    status: Literal["confirmed", "added"]
    origin: Literal["agent", "advocate"]


class AgentFindingOut(_FindingId):
    """Lawyer view of a finding the review agent raised (it passed the Layer 5 gate before storage)."""
    model_config = ConfigDict(extra="forbid")

    origin: Literal["agent"] = "agent"
    version_no: int | None = None
    layer: str | None = None            # the layer's name, e.g. "STATUTORY"; null only for a damaged old row
    severity: Severity
    clause_reference: str | None = None
    description: str
    rule_applied: str | None = None
    remedy_suggested: str | None = None
    citation: str | None = None
    citation_type: str | None = None
    status: Literal["pending", "confirmed", "overridden", "added"]
    advocate_notes: str | None = None
    adjudicated_at: datetime | None = None


class AdvocateFindingOut(_FindingId):
    """Lawyer view of a finding a lawyer added. Separate from the agent model on purpose: it has no
    layer, no agent citation and no gate result, and must never be shown as if it had."""
    model_config = ConfigDict(extra="forbid")

    origin: Literal["advocate"] = "advocate"
    version_no: int | None = None
    severity: Severity
    clause_reference: str | None = None
    description: str
    rule_applied: str | None = None
    remedy_suggested: str | None = None
    status: Literal["added"] = "added"
    advocate_notes: str | None = None
    adjudicated_at: datetime | None = None


# One list for the lawyer, merged, each item tagged by `origin`.
LawyerFindingOut = Annotated[Union[AgentFindingOut, AdvocateFindingOut], Field(discriminator="origin")]


def lawyer_finding_out(row: dict) -> AgentFindingOut | AdvocateFindingOut:
    """Build the lawyer view from a `findings` row. Origin is derived from the lawyer's action
    ('add' = lawyer-added), never from the row's content."""
    if row.get("advocate_action") == "add":
        return AdvocateFindingOut(
            finding_id=row["id"], version_no=row.get("version_no"), severity=row["severity"],
            clause_reference=row.get("clause_reference"), description=row["description"],
            rule_applied=row.get("rule_applied"), remedy_suggested=row.get("remedy_suggested"),
            advocate_notes=row.get("advocate_notes"), adjudicated_at=row.get("adjudicated_at"))
    layer = row.get("layer")
    return AgentFindingOut(
        finding_id=row["id"], version_no=row.get("version_no"),
        layer=Layer(layer).name if layer is not None else None, severity=row["severity"],
        clause_reference=row.get("clause_reference"), description=row["description"],
        rule_applied=row.get("rule_applied"), remedy_suggested=row.get("remedy_suggested"),
        citation=row.get("citation"), citation_type=row.get("citation_type"),
        status=row.get("status") or "pending", advocate_notes=row.get("advocate_notes"),
        adjudicated_at=row.get("adjudicated_at"))
