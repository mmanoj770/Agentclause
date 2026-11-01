"""NormalizedDocument: a contract after intake normalisation (R2), the input to layers R3-R9."""
from datetime import date
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator

# contract_types.code values (migration 03 seed), plus "other". POST /documents and run_review()
# key on these codes, so intake must use the same ones.
DOCUMENT_TYPES = (
    "nda", "founders_agreement", "sha", "vendor_supplier", "employment_contract",
    "consultant_freelancer", "commercial_lease", "distributor_dealership", "equipment_lease", "esop",
    "intercreditor_hypothecation", "jva", "leave_and_license", "loan_debt", "msa",
    "non_compete_non_solicit", "partnership_deed", "sla", "term_sheet_investment", "other",
)
DocumentType = Enum("DocumentType", {c.upper(): c for c in DOCUMENT_TYPES}, type=str)


class ClauseType(str, Enum):
    """Clause kinds intake can report. Names follow the rules engine's clause ids where they overlap."""
    CONFIDENTIALITY = "confidentiality"
    CONFIDENTIAL_INFO_DEFINITION = "confidential_info_definition"
    OBLIGATIONS = "obligations"
    EXCLUSIONS = "exclusions"
    TERM = "term"
    RETURN_DESTRUCTION = "return_destruction"
    RESIDUALS = "residuals"
    GOVERNING_LAW = "governing_law"
    DISPUTE_RESOLUTION = "dispute_resolution"
    REMEDIES = "remedies"
    IP_ASSIGNMENT = "ip_assignment"
    NON_COMPETE = "non_compete"
    NON_SOLICIT = "non_solicit"
    REMUNERATION = "remuneration"
    TERMINATION = "termination"
    INDEMNITY = "indemnity"
    LIMITATION_OF_LIABILITY = "limitation_of_liability"
    OTHER = "other"


class NormalizedDocument(BaseModel):
    """Structured representation of a contract after intake normalisation (R2)."""
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        json_schema_extra={"example": {
            "parties": ["ACME Corp", "XYZ Startup Private Limited"],
            "execution_date": "2026-10-15",
            "effective_date": "2026-10-15",
            "document_type": "nda",
            "jurisdiction": "India",
            "clauses": ["confidentiality", "confidential_info_definition", "governing_law", "term"],
            "full_text": "CONFIDENTIALITY AGREEMENT...",
            "extraction_confidence": None,
        }},
    )

    parties: list[str] = Field(min_length=2, description="Party names as written in the contract (at least 2).")
    execution_date: date | None = Field(default=None, description="Date the contract was signed, if stated.")
    effective_date: date | None = Field(default=None, description="Effective date, if stated.")
    document_type: DocumentType = Field(description="A contract_types code, or \"other\".")
    jurisdiction: str | None = Field(default=None, description="Governing jurisdiction, e.g. India, Maharashtra.")
    clauses: list[ClauseType] = Field(min_length=1, description="Clause kinds found, without duplicates.")
    full_text: str = Field(min_length=1, description="The contract text, cleaned (see clean_text()).")
    extraction_confidence: float | None = Field(
        default=None, ge=0.0, le=1.0,
        description="Not measured yet, so None. Never fill this with a made-up constant.",
    )

    @field_validator("parties")
    @classmethod
    def _distinct_parties(cls, v: list[str]) -> list[str]:
        if any(not p for p in v):
            raise ValueError("party names must not be blank")
        if len({p.casefold() for p in v}) < 2:
            raise ValueError("at least 2 distinct parties are required")
        return v

    @field_validator("clauses")
    @classmethod
    def _dedupe(cls, v: list[ClauseType]) -> list[ClauseType]:
        return list(dict.fromkeys(v))
