"""run_review(): the single entry point for a rules-based review (R3 completeness + R4 rule engine)."""
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.auth.dependencies import CurrentUser, get_current_user
from app.rules.completeness import CompletenessChecker
from app.rules.engine import RuleEvaluator
from app.rules.schema import Rule, RuleLoader
from app.schemas.finding import Finding, Severity
from app.schemas.normalized_document import NormalizedDocument

RULES_DIR = Path(__file__).parent / "rules"
_SEVERITY_ORDER = {Severity.CRITICAL: 0, Severity.HIGH: 1, Severity.MEDIUM: 2, Severity.LOW: 3}


@lru_cache
def _rules(strict: bool) -> tuple[Rule, ...]:
    return tuple(RuleLoader(RULES_DIR, strict=strict).load())


@lru_cache
def _checkers() -> dict[str, CompletenessChecker]:
    nda = CompletenessChecker()
    return {nda.contract_type: nda}


async def run_review(contract_text: str, contract_type_id: str, *, strict: bool = False,
                     found_clauses: frozenset[str] | set[str] = frozenset()) -> list[Finding]:
    """Review normalised contract text and return findings, most severe first.

    contract_type_id is a contract_types code, e.g. "nda".
    strict=False (the default, while every rule is unverified) also runs unverified rules; their
    findings are capped at LOW. strict=True runs verified rules only.
    found_clauses: clause ids intake already located (see run_review_normalized).
    """
    contract_type = contract_type_id.strip().lower()
    rule_findings = RuleEvaluator(list(_rules(strict))).evaluate(contract_text, contract_type)

    checker = _checkers().get(contract_type)
    reported = {f.rule_applied for f in rule_findings}
    completeness = [f for f in (checker.check(contract_text, found_clauses) if checker else [])
                    if f.rule_applied not in reported]

    return sorted(rule_findings + completeness,
                  key=lambda f: (_SEVERITY_ORDER[f.severity], f.layer, f.rule_applied))


async def run_review_normalized(doc: NormalizedDocument, *, strict: bool = False) -> list[Finding]:
    """run_review() for intake (R2) output: reviews doc.full_text, and the completeness checker also
    counts the clauses intake found."""
    return await run_review(doc.full_text, doc.document_type.value, strict=strict,
                            found_clauses=doc.clause_types())


router = APIRouter(prefix="/reviews", tags=["reviews"])


class ReviewRequest(BaseModel):
    contract_text: str = Field(min_length=1, max_length=500_000)
    contract_type_id: str = Field(min_length=1, max_length=64)


@router.post("")
async def create_review(body: ReviewRequest,
                        user: CurrentUser = Depends(get_current_user)) -> list[Finding]:
    return await run_review(body.contract_text, body.contract_type_id)
