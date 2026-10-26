"""NormalizedDocument: a contract after intake normalisation (R2), the input to layers R3-R9."""
from datetime import date
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.rules.clauses import CLAUSES

# contract_types.code values (migration 03 seed). POST /documents and run_review() key on these codes,
# so intake uses the same ones and never invents a type.
DOCUMENT_TYPES = (
    "nda", "founders_agreement", "sha", "vendor_supplier", "employment_contract",
    "consultant_freelancer", "commercial_lease", "distributor_dealership", "equipment_lease", "esop",
    "intercreditor_hypothecation", "jva", "leave_and_license", "loan_debt", "msa",
    "non_compete_non_solicit", "partnership_deed", "sla", "term_sheet_investment",
)
DocumentType = Enum("DocumentType", {c.upper(): c for c in DOCUMENT_TYPES}, type=str)

# The clause ids of the rules engine's clause registry (the ids nda_required_clauses.json uses), plus
# "other", so the completeness checker (R3) can read intake's output without a mapping.
ClauseType = Enum(
    "ClauseType",
    {**{c.upper().replace("-", "_"): c for c in CLAUSES}, "OTHER": "other"},
    type=str,
)


class Clause(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    clause_number: str | None = Field(default=None, max_length=20, description="As numbered in the text, e.g. \"4.2\".")
    heading: str | None = Field(default=None, max_length=200, description="The clause heading, if it has one.")
    text: str = Field(min_length=1, description="The clause text, an exact substring of full_text.")
    clause_type: ClauseType = Field(description="A clause registry id, or \"other\".")


class NormalizedDocument(BaseModel):
    """Structured representation of a contract after intake normalisation (R2)."""
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        json_schema_extra={"example": {
            "parties": ["ACME Corp", "XYZ Startup Private Limited"],
            "execution_date": "2026-10-15",
            "effective_date": None,
            "document_type": "nda",
            "jurisdiction": "India",
            "clauses": [{"clause_number": "3", "heading": "GOVERNING LAW", "clause_type": "governing-law",
                         "text": "This Agreement shall be governed by the laws of India."}],
            "full_text": "CONFIDENTIALITY AGREEMENT...",
            "extraction_model": "gemini-3.5-flash-lite",
            "extraction_attempts": 1,
        }},
    )

    parties: list[str] = Field(min_length=2, description="Party names as written in the contract (at least 2).")
    execution_date: date | None = Field(default=None, description="Date the contract was signed, if stated.")
    effective_date: date | None = Field(default=None, description="Effective date, if stated.")
    document_type: DocumentType = Field(description="A contract_types code.")
    jurisdiction: str | None = Field(default=None, description="Governing jurisdiction, e.g. India, Maharashtra.")
    clauses: list[Clause] = Field(min_length=1, description="Clauses found, in document order.")
    full_text: str = Field(min_length=1, description="The contract text, cleaned (see intake.service.clean_text).")
    extraction_model: str = Field(min_length=1, description="The model that produced the extraction.")
    extraction_attempts: int = Field(ge=1, description="How many model calls it took to get a valid extraction.")

    @field_validator("parties")
    @classmethod
    def _distinct_parties(cls, v: list[str]) -> list[str]:
        if any(not p for p in v):
            raise ValueError("party names must not be blank")
        if len({p.casefold() for p in v}) < 2:
            raise ValueError("at least 2 distinct parties are required")
        return v

    def clause_types(self) -> set[str]:
        """Registry ids of the clauses found (without "other"), for the completeness checker."""
        return {c.clause_type.value for c in self.clauses} - {"other"}
