"""run_review(): the single entry point for a rules-based review (R3 completeness + R4 rule engine)."""
from datetime import date
from enum import Enum
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.auth.dependencies import CurrentUser, get_current_user
from app.rules.completeness import CompletenessChecker
from app.rules.engine import RuleEvaluator
from app.rules.schema import Rule, RuleLoader, VerificationStatus, base_rule_id
from app.schemas.finding import Finding, Severity

RULES_DIR = Path(__file__).parent / "rules"
_SEVERITY_ORDER = {Severity.CRITICAL: 0, Severity.HIGH: 1, Severity.MEDIUM: 2, Severity.LOW: 3}
DEMO_NOTICE = ("Demo mode: these findings include rules no lawyer has verified. "
               "Do not rely on them or show them to users as advice.")


@lru_cache(maxsize=16)
def _rules(strict: bool, on: date) -> tuple[Rule, ...]:
    return tuple(RuleLoader(RULES_DIR, strict=strict, on=on).load())


@lru_cache
def _checkers() -> dict[str, CompletenessChecker]:
    nda = CompletenessChecker()
    return {nda.contract_type: nda}


class ReviewFinding(Finding):
    """A Finding plus the verification status of the rule that raised it.

    verification_status is not a `findings` column; to_insert_row() leaves it out.
    """
    verification_status: VerificationStatus = Field(
        description="Whether a lawyer has verified the rule (or completeness config) behind this finding.",
    )


async def run_review(contract_text: str, contract_type_id: str, *, strict: bool = True,
                     on: date | None = None) -> list[ReviewFinding]:
    """Review normalised contract text and return findings, most severe first.

    contract_type_id is a contract_types code, e.g. "nda".
    strict=True (the default) runs verified rules and verified completeness configs only.
    strict=False is for demos and tests: it also runs unverified ones, whose findings are capped at LOW.
    on picks the rule versions in force on that date (default today).
    """
    day = on or date.today()
    contract_type = contract_type_id.strip().lower()
    rules = _rules(strict, day)
    rule_status = {r.versioned_id: r.verification_status for r in rules}
    rule_findings = [ReviewFinding(**f.model_dump(), verification_status=rule_status[f.rule_applied])
                     for f in RuleEvaluator(list(rules), today=day).evaluate(contract_text, contract_type)]

    checker = _checkers().get(contract_type)
    if checker and strict and not checker.verified:
        checker = None
    reported = {base_rule_id(f.rule_applied) for f in rule_findings}
    completeness = [ReviewFinding(**f.model_dump(), verification_status=checker.verification_status)
                    for f in (checker.check(contract_text) if checker else [])
                    if f.rule_applied not in reported]

    return sorted(rule_findings + completeness,
                  key=lambda f: (_SEVERITY_ORDER[f.severity], f.layer, f.rule_applied))


router = APIRouter(prefix="/reviews", tags=["reviews"])


class ReviewRequest(BaseModel):
    contract_text: str = Field(min_length=1, max_length=500_000)
    contract_type_id: str = Field(min_length=1, max_length=64)


class ReviewStatus(str, Enum):
    OK = "ok"                                                # strict: verified findings returned
    NO_VERIFIED_RULES_MATCHED = "no_verified_rules_matched"  # strict: nothing verified fired
    DEMO_INCLUDES_UNVERIFIED = "demo_includes_unverified"    # strict=false: never treat as verified


class ReviewResponse(BaseModel):
    strict_mode: bool
    status: ReviewStatus
    notice: str | None = Field(default=None, description="Set in demo mode; say it wherever findings are shown.")
    findings: list[ReviewFinding]


@router.post("")
async def create_review(body: ReviewRequest,
                        strict: bool = Query(True, description="false = demo/testing only: includes unverified rules."),
                        user: CurrentUser = Depends(get_current_user)) -> ReviewResponse:
    findings = await run_review(body.contract_text, body.contract_type_id, strict=strict)
    if not strict:
        return ReviewResponse(strict_mode=False, status=ReviewStatus.DEMO_INCLUDES_UNVERIFIED,
                              notice=DEMO_NOTICE, findings=findings)
    status = ReviewStatus.OK if findings else ReviewStatus.NO_VERIFIED_RULES_MATCHED
    return ReviewResponse(strict_mode=True, status=status, findings=findings)
