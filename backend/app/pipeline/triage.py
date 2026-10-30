"""Risk triage (R9): routes a reviewed document to a review depth.

    triage(findings)  ->  {"review_tier": "standard" | "enhanced" | "senior_counsel", "score": float, "reasons": [...]}

The score is the sum of a weight per finding severity, plus the R7 risk-asymmetry score times its
weight (R7 doesn't exist yet, so callers pass 0). The tier is the highest threshold the score reaches,
and any critical finding gives at least "enhanced". Weights and thresholds live in config/triage.json,
which is a PLACEHOLDER until a lawyer sets them.

save_triage() stores the tier in documents.triage_tier (migration 04; the lawyer queue already reads
it) and the score and reasons in an audit row. Reasons name rule IDs and severities only, never
contract text.
"""
import json
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.audit import write_audit
from app.schemas.finding import Finding, Severity

CONFIG_PATH = Path(__file__).parent / "config" / "triage.json"
TIERS = ("standard", "enhanced", "senior_counsel")      # lowest to highest; documents.triage_tier check (migration 04)
CRITICAL_MINIMUM_TIER = "enhanced"


class SeverityWeights(BaseModel):
    model_config = ConfigDict(extra="forbid")
    critical: float = Field(ge=0)
    high: float = Field(ge=0)
    medium: float = Field(ge=0)
    low: float = Field(ge=0)


class Thresholds(BaseModel):
    """The lowest score that reaches each tier above standard."""
    model_config = ConfigDict(extra="forbid")
    enhanced: float = Field(gt=0)
    senior_counsel: float = Field(gt=0)

    @model_validator(mode="after")
    def _ordered(self) -> "Thresholds":
        if self.senior_counsel <= self.enhanced:
            raise ValueError("thresholds.senior_counsel must be above thresholds.enhanced")
        return self


class TriageConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str = Field(min_length=1, description="\"PLACEHOLDER\" until a lawyer sets the values.")
    note: str | None = None
    severity_weights: SeverityWeights
    asymmetry_weight: float = Field(ge=0)
    thresholds: Thresholds


def load_config(path: Path = CONFIG_PATH) -> TriageConfig:
    return TriageConfig.model_validate(json.loads(Path(path).read_text()))


@lru_cache
def _default_config() -> TriageConfig:
    return load_config()


def _tier_for(score: float, thresholds: Thresholds) -> str:
    if score >= thresholds.senior_counsel:
        return "senior_counsel"
    if score >= thresholds.enhanced:
        return "enhanced"
    return "standard"


def triage(findings: list[Finding], *, asymmetry_score: float = 0.0, config: TriageConfig | None = None) -> dict:
    """Score the findings and pick a review tier. The reasons list says which findings drove it."""
    config = config or _default_config()
    weights = config.severity_weights
    points = [(f, getattr(weights, f.severity.value)) for f in findings]
    score = round(sum(p for _, p in points) + config.asymmetry_weight * asymmetry_score, 6)
    tier = _tier_for(score, config.thresholds)

    reasons = [f"{f.rule_applied} ({f.severity.value}): +{p:g}"
               for f, p in sorted(points, key=lambda fp: (-fp[1], fp[0].rule_applied)) if p > 0]
    if asymmetry_score:
        reasons.append(f"risk asymmetry {asymmetry_score:g} x {config.asymmetry_weight:g}: "
                       f"+{config.asymmetry_weight * asymmetry_score:g}")
    if tier == "standard":
        reasons.append(f"score {score:g} is below the enhanced threshold {config.thresholds.enhanced:g}")
    else:
        reasons.append(f"score {score:g} reaches the {tier} threshold {getattr(config.thresholds, tier):g}")

    critical = sorted(f.rule_applied for f in findings if f.severity is Severity.CRITICAL)
    if critical and TIERS.index(tier) < TIERS.index(CRITICAL_MINIMUM_TIER):
        tier = CRITICAL_MINIMUM_TIER
        reasons.append(f"critical finding(s) {', '.join(critical)}: at least {CRITICAL_MINIMUM_TIER}")
    return {"review_tier": tier, "score": score, "reasons": reasons}


def save_triage(conn, document_id, result: dict, *, config: TriageConfig | None = None) -> None:
    """Store the tier on the document and the score and reasons in the audit log.

    The pipeline's R9 hook calls this inside the same transaction that saves the findings.
    """
    if result["review_tier"] not in TIERS:
        raise ValueError(f"unknown review tier {result['review_tier']!r}")
    config = config or _default_config()
    conn.execute("update documents set triage_tier = %s where id = %s", (result["review_tier"], document_id))
    write_audit(conn, document_id=document_id, actor_id=None, actor_role="system", action="triage_assigned",
                details={"review_tier": result["review_tier"], "score": result["score"],
                         "reasons": result["reasons"], "config_status": config.status})
