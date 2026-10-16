"""Finding Schema (R1): the one shape every review-agent finding takes.

Mirrors the `findings` table (migrations 05 and 10). Two fields have no column yet:
`citation` is carried in the model but not stored, and `status` is stored as
`advocate_action`. See README.md in this folder.
"""
from enum import Enum, IntEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator


class Layer(IntEnum):
    """Review layer. Values are what the `findings.layer` smallint column stores (0-6)."""
    STRUCTURAL = 0
    FUNCTIONAL = 1
    RISK = 2
    LEGAL = 3


class Severity(str, Enum):
    """Matches the `findings_severity_check` constraint. There is no INFO: the table rejects it."""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class FindingStatus(str, Enum):
    """Review status, stored in `findings.advocate_action` (PENDING is stored as null)."""
    PENDING = "pending"
    CONFIRMED = "confirmed"
    OVERRIDDEN = "overridden"
    ADDED = "added"


_STATUS_TO_ACTION = {
    FindingStatus.PENDING: None,
    FindingStatus.CONFIRMED: "confirm",
    FindingStatus.OVERRIDDEN: "override",
    FindingStatus.ADDED: "add",
}
_ACTION_TO_STATUS = {v: k for k, v in _STATUS_TO_ACTION.items()}

# Columns of public.findings that a Finding writes on insert.
INSERT_COLUMNS = (
    "id", "document_id", "document_version_id", "layer", "severity", "clause_reference",
    "description", "rule_applied", "remedy_suggested", "advocate_action",
)


class Finding(BaseModel):
    """A single finding returned by the review agent."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    finding_id: UUID = Field(
        default_factory=uuid4,
        description="Unique ID of the finding. Stored as `findings.id`.",
    )
    layer: Layer = Field(
        description="Review layer that produced the finding. Accepts the name (\"RISK\") or the "
                    "stored integer (2); serialises to the name in JSON.",
    )
    severity: Severity = Field(description="How serious the issue is: critical, high, medium or low.")
    clause_reference: str = Field(
        min_length=1, max_length=200,
        description="Where in the contract the issue sits, e.g. \"Clause 12.1\" or \"Missing\".",
    )
    description: str = Field(min_length=1, description="Plain-language statement of the issue.")
    rule_applied: str = Field(
        pattern=r"^[A-Z][A-Z0-9_]*$", max_length=100,
        description="Visible rule ID that triggered the finding, e.g. \"NDA_GOVERNING_LAW_MISSING\".",
    )
    remedy_suggested: str = Field(min_length=1, description="What to change to resolve the issue.")
    citation: str = Field(
        min_length=1,
        description="Legal source backing the rule, e.g. a statute section. Not stored yet: the "
                    "findings table has no citation column.",
    )
    status: FindingStatus = Field(
        default=FindingStatus.PENDING,
        description="Review status. Stored as `findings.advocate_action`.",
    )

    @field_validator("layer", mode="before")
    @classmethod
    def _layer_by_name(cls, v: Any) -> Any:
        if isinstance(v, str) and v.upper() in Layer.__members__:
            return Layer[v.upper()]
        return v

    @field_serializer("layer", when_used="json")
    def _layer_name(self, v: Layer) -> str:
        return v.name

    def to_insert_row(self, document_id: UUID, document_version_id: UUID) -> dict[str, Any]:
        """Return a column -> value dict that can be inserted into `findings` as-is.

        Raises ValueError if the row would break a table constraint.
        """
        row = {
            "id": self.finding_id,
            "document_id": document_id,
            "document_version_id": document_version_id,
            "layer": int(self.layer),
            "severity": self.severity.value,
            "clause_reference": self.clause_reference,
            "description": self.description,
            "rule_applied": self.rule_applied,
            "remedy_suggested": self.remedy_suggested,
            "advocate_action": _STATUS_TO_ACTION[self.status],
        }
        if not 0 <= row["layer"] <= 6:
            raise ValueError("layer must be between 0 and 6 (findings_layer_check)")
        if row["severity"] not in {"low", "medium", "high", "critical"}:
            raise ValueError("severity breaks findings_severity_check")
        if not row["description"]:
            raise ValueError("description is not null")
        return row

    @classmethod
    def from_db_row(cls, row: dict[str, Any], citation: str) -> "Finding":
        """Build a Finding from a `findings` row. `citation` must be supplied: the table doesn't store it."""
        return cls(
            finding_id=row["id"],
            layer=row["layer"],
            severity=row["severity"],
            clause_reference=row["clause_reference"],
            description=row["description"],
            rule_applied=row["rule_applied"],
            remedy_suggested=row["remedy_suggested"],
            citation=citation,
            status=_ACTION_TO_STATUS[row["advocate_action"]],
        )


def check_table_matches(conn) -> list[str]:
    """Compare INSERT_COLUMNS with the live `findings` table. Returns the problems; empty means OK."""
    cols = {
        r["column_name"] if isinstance(r, dict) else r[0]
        for r in conn.execute(
            "select column_name from information_schema.columns "
            "where table_schema = 'public' and table_name = 'findings'"
        ).fetchall()
    }
    return [f"findings has no column {c!r}" for c in INSERT_COLUMNS if c not in cols]
