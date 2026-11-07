"""Completeness checker (R3): reports required clauses that a contract lacks. NDA only for the MVP."""
import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.rules.clauses import CLAUSES, internal_citation, normalise
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


class CompletenessResult(BaseModel):
    findings: list[Finding]
    rules_total: int
    rules_evaluated: int
    rules_skipped_unverified: list[str]
    review_status: str


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

    def check(self, text: str, found: frozenset[str] | set[str] = frozenset()) -> list[Finding]:
        """found: clause ids intake (R2) located in the text. Such a clause counts as present even when
        the keyword patterns miss its wording; intake only reports clauses whose text it quoted verbatim."""
        normalised = normalise(text)
        verified = self.verified
        findings = []
        for req in self.config.required:
            clause = CLAUSES[req.clause]
            if req.clause in found or clause.present_in(normalised):
                continue
            findings.append(Finding(
                layer=Layer.COMPLETENESS,
                severity=finding_severity(req.severity, verified),
                clause_reference="Missing",
                description=f"Required clause not found: {clause.label}.",
                rule_applied=rule_id_for(self.contract_type, req.clause),
                remedy_suggested=f"Add a {clause.label.lower()} clause.",
                citation=internal_citation(self.contract_type, req.clause),
                citation_type=CitationType.INTERNAL_BASELINE,
            ))
        return findings

    def check_with_coverage(self, text: str, *, strict: bool = False,
                            found: frozenset[str] | set[str] = frozenset()) -> CompletenessResult:
        """Evaluate with explicit coverage metrics when strict mode skips unverified configs."""
        rules_total = len(self.config.required)
        if strict and not self.verified:
            return CompletenessResult(
                findings=[],
                rules_total=rules_total,
                rules_evaluated=0,
                rules_skipped_unverified=self.rule_ids,
                review_status="no_rules_verified",
            )
        findings = self.check(text, found)
        return CompletenessResult(
            findings=findings,
            rules_total=rules_total,
            rules_evaluated=rules_total,
            rules_skipped_unverified=[],
            review_status="complete",
        )
