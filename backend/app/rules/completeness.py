"""Completeness checker (R3): reports required clauses that a contract lacks. NDA only for the MVP."""
import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.rules.clauses import CLAUSES, normalise
from app.rules.engine import finding_severity
from app.rules.schema import VerificationStatus
from app.schemas.finding import CitationType, Finding, Layer, Severity

CONFIG_DIR = Path(__file__).parent / "config"


class RequiredClause(BaseModel):
    model_config = ConfigDict(extra="forbid")
    clause: str
    severity: Severity

    @field_validator("clause")
    @classmethod
    def _known(cls, v: str) -> str:
        if v not in CLAUSES:
            raise ValueError(f"unknown clause id {v!r}; known: {sorted(CLAUSES)}")
        return v


class CompletenessConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    contract_type: str
    verification_status: VerificationStatus
    required: list[RequiredClause] = Field(min_length=1)


def rule_id_for(contract_type: str, clause: str) -> str:
    """e.g. ('nda', 'governing-law') -> NDA_GOVERNING_LAW_MISSING. Rule files use the same IDs,
    so run_review can drop a completeness finding that a rule already reported."""
    return f"{contract_type}_{clause}_missing".upper().replace("-", "_")


class CompletenessChecker:
    """Checks one contract type's required clauses. Findings are LOW while the config is unverified."""

    def __init__(self, config_path: Path = CONFIG_DIR / "nda_required_clauses.json"):
        self.config = CompletenessConfig.model_validate(json.loads(Path(config_path).read_text()))

    @property
    def contract_type(self) -> str:
        return self.config.contract_type

    @property
    def verification_status(self) -> VerificationStatus:
        return self.config.verification_status

    @property
    def verified(self) -> bool:
        return self.config.verification_status is VerificationStatus.VERIFIED

    @property
    def rule_ids(self) -> list[str]:
        """The rule_applied of each required-clause check, in config order."""
        return [rule_id_for(self.contract_type, req.clause) for req in self.config.required]

    def check(self, text: str) -> list[Finding]:
        normalised = normalise(text)
        verified = self.verified
        findings = []
        for req in self.config.required:
            clause = CLAUSES[req.clause]
            if clause.present_in(normalised):
                continue
            findings.append(Finding(
                layer=Layer.COMPLETENESS,
                severity=finding_severity(req.severity, verified),
                clause_reference="Missing",
                description=f"Required clause not found: {clause.label}.",
                rule_applied=rule_id_for(self.contract_type, req.clause),
                remedy_suggested=f"Add a {clause.label.lower()} clause.",
                citation=f"Internal: {self.contract_type.upper()} completeness baseline, {clause.label}",
                citation_type=CitationType.INTERNAL_BASELINE,
            ))
        return findings
