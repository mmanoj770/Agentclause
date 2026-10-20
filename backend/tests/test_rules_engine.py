import asyncio
import json
from datetime import date

import pytest

from app.auth.dependencies import CurrentUser, get_current_user
from app.rules.api import RULES_DIR, run_review
from app.rules.completeness import CompletenessChecker
from app.rules.engine import RuleEvaluator
from app.rules.schema import Rule, RuleError, RuleLoader, RuleValidator
from app.schemas.finding import Layer, Severity

VALID = {
    "rule_id": "NDA_GOVERNING_LAW_MISSING",
    "statute": "Internal",
    "section": "NDA baseline, governing law",
    "applies_to": ["nda"],
    "condition": "missing_clause('governing-law')",
    "severity": "HIGH",
    "remedy_suggested": "Add a governing-law clause.",
    "effective_from": "2024-01-01",
    "verification_status": "unverified",
}

CLEAN_NDA = """
MUTUAL NON-DISCLOSURE AGREEMENT

1. Definitions. "Confidential Information" means all information disclosed by either party.
2. Exclusions. Confidential Information does not include information in the public domain.
3. Obligations of the Receiving Party. The Receiving Party shall keep the Confidential Information
   confidential and shall not disclose it to any third party.
4. Term. This Agreement shall remain in force for a period of three years.
5. Return of Information. On request the Receiving Party shall return or destroy all Confidential Information.
6. Residuals. Nothing restricts use of general skills retained in unaided memory (residuals).
7. Governing Law. This Agreement is governed by the laws of India; courts at Bengaluru have jurisdiction.
"""

NDA_NO_GOVERNING_LAW = CLEAN_NDA.replace(
    "7. Governing Law. This Agreement is governed by the laws of India; courts at Bengaluru have jurisdiction.", "")

NDA_WITH_RESTRAINT = CLEAN_NDA + "\n8. Non-Compete. The Recipient shall not engage in any business that competes.\n"


def rule(**changes) -> Rule:
    return RuleValidator.validate({**VALID, **changes})


def review(text, contract_type="nda", **kw):
    return asyncio.run(run_review(text, contract_type, **kw))


# --- rule files -------------------------------------------------------------------------------

def test_valid_rule_loads():
    r = rule()
    assert r.severity is Severity.HIGH and not r.verified
    assert r.citation == "Internal: NDA baseline, governing law"


def test_statute_citation_matches_migration_18_pattern():
    r = rule(statute="Indian Contract Act, 1872", section="27")
    assert r.citation == "Indian Contract Act, 1872, s. 27"


@pytest.mark.parametrize("change", [
    {"rule_id": "lowercase_id"},
    {"severity": "info"},
    {"condition": "missing_clause('no-such-clause')"},
    {"condition": "__import__('os').system('ls')"},
    {"condition": "contains_text()"},
    {"condition": "missing_clause('governing-law', 'term')"},
    {"applies_to": []},
    {"statute": "Indian Contract Act"},                  # no year
    {"statute": "Indian Contract Act, 1872", "section": "General practice"},
    {"effective_from": "someday"},
    {"verification_status": "approved"},
    {"extra_field": 1},
])
def test_malformed_rule_rejected(change):
    with pytest.raises(RuleError):
        rule(**change)


def test_malformed_file_rejected_with_its_name(tmp_path):
    (tmp_path / "broken.json").write_text("{not json")
    with pytest.raises(RuleError, match="broken.json"):
        RuleLoader(tmp_path).load()


def test_duplicate_rule_id_rejected(tmp_path):
    for name in ("a.json", "b.json"):
        (tmp_path / name).write_text(json.dumps(VALID))
    with pytest.raises(RuleError, match="duplicate"):
        RuleLoader(tmp_path, strict=False).load()


def test_shipped_rule_files_are_valid():
    ids = {r.rule_id for r in RuleLoader(RULES_DIR, strict=False).load()}
    assert ids == {"NDA_GOVERNING_LAW_MISSING", "NDA_CONFIDENTIAL_INFO_DEFINITION_MISSING",
                   "ICA_S27_RESTRAINT_OF_TRADE"}


def test_unverified_rules_skipped_in_strict_mode(tmp_path):
    (tmp_path / "unverified.json").write_text(json.dumps(VALID))
    (tmp_path / "verified.json").write_text(json.dumps(
        {**VALID, "rule_id": "VERIFIED_RULE", "verification_status": "verified"}))
    assert [r.rule_id for r in RuleLoader(tmp_path).load()] == ["VERIFIED_RULE"]
    assert len(RuleLoader(tmp_path, strict=False).load()) == 2


# --- evaluator --------------------------------------------------------------------------------

def test_rule_fires_when_clause_missing():
    [f] = RuleEvaluator([rule()]).evaluate(NDA_NO_GOVERNING_LAW, "nda")
    assert f.rule_applied == "NDA_GOVERNING_LAW_MISSING"
    assert f.clause_reference == "Missing" and f.layer is Layer.COMPLETENESS


def test_rule_does_not_fire_when_clause_present():
    assert RuleEvaluator([rule()]).evaluate(CLEAN_NDA, "nda") == []


def test_rule_ignores_other_contract_types():
    assert RuleEvaluator([rule()]).evaluate(NDA_NO_GOVERNING_LAW, "sha") == []


def test_rule_not_yet_effective_is_skipped():
    later = rule(effective_from="2030-01-01")
    assert RuleEvaluator([later], today=date(2026, 10, 20)).evaluate(NDA_NO_GOVERNING_LAW, "nda") == []


def test_unverified_rule_capped_at_low_verified_keeps_severity():
    [low] = RuleEvaluator([rule()]).evaluate(NDA_NO_GOVERNING_LAW, "nda")
    [high] = RuleEvaluator([rule(verification_status="verified")]).evaluate(NDA_NO_GOVERNING_LAW, "nda")
    assert low.severity is Severity.LOW and high.severity is Severity.HIGH


def test_contains_text_locates_the_clause():
    s27 = rule(rule_id="ICA_S27_RESTRAINT_OF_TRADE", statute="Indian Contract Act, 1872", section="27",
               condition="contains_text('non-compete', 'restraint of trade')", severity="critical",
               verification_status="verified")
    [f] = RuleEvaluator([s27]).evaluate(NDA_WITH_RESTRAINT, "nda")
    assert f.clause_reference == "Clause 8"
    assert f.layer is Layer.STATUTORY and f.severity is Severity.CRITICAL
    assert f.citation == "Indian Contract Act, 1872, s. 27"


# --- completeness -----------------------------------------------------------------------------

def test_completeness_clean_nda_has_nothing_missing():
    assert CompletenessChecker().check(CLEAN_NDA) == []


def test_completeness_reports_every_missing_clause_at_low_while_unverified():
    findings = CompletenessChecker().check("This is a short letter with no clauses at all.")
    assert len(findings) == 8
    assert {f.severity for f in findings} == {Severity.LOW}
    assert all(f.layer is Layer.COMPLETENESS and f.citation.startswith("Internal:") for f in findings)


# --- run_review -------------------------------------------------------------------------------

def test_run_review_returns_findings():
    findings = review(NDA_NO_GOVERNING_LAW)
    assert [f.rule_applied for f in findings] == ["NDA_GOVERNING_LAW_MISSING"]


def test_run_review_reports_a_missing_clause_once():
    # The rule file and the completeness checker both cover governing law; only one finding comes back.
    ids = [f.rule_applied for f in review(NDA_NO_GOVERNING_LAW)]
    assert ids.count("NDA_GOVERNING_LAW_MISSING") == 1


def test_run_review_clean_nda_returns_empty_list():
    assert review(CLEAN_NDA) == []


def test_run_review_strict_mode_runs_no_unverified_rules():
    assert [f.rule_applied for f in review(NDA_WITH_RESTRAINT, strict=True)] == []
    assert "ICA_S27_RESTRAINT_OF_TRADE" in [f.rule_applied for f in review(NDA_WITH_RESTRAINT)]


def test_run_review_sorted_by_severity():
    findings = review("A bare page.")
    order = ["critical", "high", "medium", "low"]
    assert [order.index(f.severity.value) for f in findings] == sorted(order.index(f.severity.value) for f in findings)


def test_reviews_endpoint(client):
    from app.main import app
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(id="u", email=None, role="startup_user", org_id=None)
    try:
        r = client.post("/reviews", json={"contract_text": NDA_NO_GOVERNING_LAW, "contract_type_id": "nda"})
        assert r.status_code == 200
        assert [f["rule_applied"] for f in r.json()] == ["NDA_GOVERNING_LAW_MISSING"]
        assert client.post("/reviews", json={"contract_text": "", "contract_type_id": "nda"}).status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_reviews_endpoint_requires_login(client):
    r = client.post("/reviews", json={"contract_text": "x", "contract_type_id": "nda"})
    assert r.status_code in (401, 403)
