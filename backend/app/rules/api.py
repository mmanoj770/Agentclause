"""run_review(): the single entry point for a rules-based review (R3 completeness + R4 rule engine)."""
import logging
from collections import Counter
from datetime import date
from enum import Enum
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.auth.dependencies import CurrentUser, get_current_user
from app.rules.completeness import CompletenessChecker
from app.rules.engine import RuleEvaluator
from app.rules.schema import (RuleGapError, RuleLoader, RuleSelection, SkippedRule, SkipReason,
                              VerificationStatus, base_rule_id, today_in_india)
from app.schemas.finding import Finding, Severity

log = logging.getLogger(__name__)

RULES_DIR = Path(__file__).parent / "rules"
_SEVERITY_ORDER = {Severity.CRITICAL: 0, Severity.HIGH: 1, Severity.MEDIUM: 2, Severity.LOW: 3}
DEMO_NOTICE = ("Demo mode: these findings include rules no lawyer has verified. "
               "Do not rely on them or show them to users as advice.")


@lru_cache(maxsize=64)
def _rules(strict: bool, on: date, contract_type: str) -> RuleSelection:
    return RuleLoader(RULES_DIR, strict=strict, on=on).select(contract_type)


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


class SkippedRules(BaseModel):
    count: int
    rules: list[SkippedRule]


class ReviewResult(BaseModel):
    evaluation_date: date = Field(description="The date whose rule versions were applied.")
    findings: list[ReviewFinding]
    skipped_rules: SkippedRules = Field(description="Every rule or completeness check that did not run, and why. "
                                                    "A missing finding is only \"nothing found\" if it is not here.")


def evaluation_date(on: date | None = None, effective_date: date | None = None) -> date:
    """on if given, else the contract's effective date if known, else today in India."""
    return on or effective_date or today_in_india()


async def run_review(contract_text: str, contract_type_id: str, *, strict: bool = True,
                     on: date | None = None, effective_date: date | None = None) -> ReviewResult:
    """Review normalised contract text: findings most severe first, plus every rule that didn't run.

    contract_type_id is a contract_types code, e.g. "nda".
    strict=True (the default) runs verified rules and verified completeness configs only.
    strict=False is for demos and tests: it also runs unverified ones, whose findings are capped at LOW.
    Rule versions are those in force on evaluation_date(on, effective_date). Pass the contract's
    effective_date when it is known (NormalizedDocument.effective_date); on overrides it.
    Raises RuleGapError if that date falls between two versions of a rule.
    """
    day = evaluation_date(on, effective_date)
    contract_type = contract_type_id.strip().lower()
    selection = _rules(strict, day, contract_type)
    skipped = list(selection.skipped)
    rule_status = {r.versioned_id: r.verification_status for r in selection.rules}
    rule_findings = [ReviewFinding(**f.model_dump(), verification_status=rule_status[f.rule_applied])
                     for f in RuleEvaluator(list(selection.rules), today=day).evaluate(contract_text, contract_type)]

    checker = _checkers().get(contract_type)
    if checker and strict and not checker.verified:
        skipped += [SkippedRule(rule_id=rule_id, version=None, reason=SkipReason.UNVERIFIED_IN_STRICT_MODE)
                    for rule_id in checker.rule_ids]
        checker = None
    reported = {base_rule_id(f.rule_applied) for f in rule_findings}
    completeness = [ReviewFinding(**f.model_dump(), verification_status=checker.verification_status)
                    for f in (checker.check(contract_text) if checker else [])
                    if f.rule_applied not in reported]

    findings = sorted(rule_findings + completeness,
                      key=lambda f: (_SEVERITY_ORDER[f.severity], f.layer, f.rule_applied))
    reasons = Counter(s.reason.value for s in skipped)
    # Counts only: never the contract text or anything taken from it.
    log.info("rules review: contract_type=%s strict=%s evaluation_date=%s rules_run=%d findings=%d skipped=%d %s",
             contract_type, strict, day.isoformat(), len(selection.rules), len(findings), len(skipped),
             " ".join(f"{k}={v}" for k, v in sorted(reasons.items())))
    return ReviewResult(evaluation_date=day, findings=findings,
                        skipped_rules=SkippedRules(count=len(skipped), rules=skipped))


router = APIRouter(prefix="/reviews", tags=["reviews"])


class ReviewRequest(BaseModel):
    contract_text: str = Field(min_length=1, max_length=500_000)
    contract_type_id: str = Field(min_length=1, max_length=64)
    effective_date: date | None = Field(default=None, description="The contract's effective date, if known. "
                                                                  "Rules in force on it apply; else today in India.")


class ReviewStatus(str, Enum):
    OK = "ok"                                                # strict: verified findings returned
    NO_VERIFIED_RULES_MATCHED = "no_verified_rules_matched"  # strict: nothing verified fired
    DEMO_INCLUDES_UNVERIFIED = "demo_includes_unverified"    # strict=false: never treat as verified


class ReviewResponse(ReviewResult):
    strict_mode: bool
    status: ReviewStatus
    notice: str | None = Field(default=None, description="Set in demo mode; say it wherever findings are shown.")


@router.post("")
async def create_review(body: ReviewRequest,
                        strict: bool = Query(True, description="false = demo/testing only: includes unverified rules."),
                        user: CurrentUser = Depends(get_current_user)) -> ReviewResponse:
    try:
        result = await run_review(body.contract_text, body.contract_type_id, strict=strict,
                                  effective_date=body.effective_date)
    except RuleGapError as e:
        # The rule files are wrong for this date. Fail loudly rather than review with a rule missing.
        raise HTTPException(500, f"Rule configuration error: {e}") from e
    if not strict:
        return ReviewResponse(**dict(result), strict_mode=False, status=ReviewStatus.DEMO_INCLUDES_UNVERIFIED,
                              notice=DEMO_NOTICE)
    status = ReviewStatus.OK if result.findings else ReviewStatus.NO_VERIFIED_RULES_MATCHED
    return ReviewResponse(**dict(result), strict_mode=True, status=status)
