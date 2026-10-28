import asyncio
import json
from datetime import date, datetime, timezone
from uuid import uuid4

import pytest

from app.auth.dependencies import CurrentUser, get_current_user
from app.rules import api
from app.rules.api import RULES_DIR, run_review
from app.rules.completeness import CompletenessChecker
from app.rules.engine import RuleEvaluator
from app.rules import schema
from app.rules.schema import (Rule, RuleError, RuleGapError, RuleLoader, RuleSelection, RuleValidator, SkipReason,
                              VerificationStatus, base_rule_id, today_in_india)
from app.schemas.finding import Layer, Severity

VALID = {
    "rule_id": "NDA_GOVERNING_LAW_MISSING",
    "statute": "Internal",
    "section": "NDA baseline, governing law",
    "applies_to": ["nda"],
    "condition": "missing_clause('governing-law')",
    "severity": "HIGH",
    "remedy_suggested": "Add a governing-law clause.",
    "version": 1,
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


def outcome(text, contract_type="nda", **kw):
    return asyncio.run(run_review(text, contract_type, **kw))


def review(text, contract_type="nda", **kw):
    return outcome(text, contract_type, **kw).findings


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
                   "ICA_S27_RESTRAINT_OF_TRADE", "ICA_S28_RESTRAINT_OF_LEGAL_PROCEEDINGS",
                   "ICA_S74_PENALTY_OR_LIQUIDATED_DAMAGES", "MSMED_S15_PAYMENT_BEYOND_45_DAYS",
                   "MSMED_S16_INTEREST_WAIVER"}


def test_unverified_rules_skipped_in_strict_mode(tmp_path):
    (tmp_path / "unverified.json").write_text(json.dumps(VALID))
    (tmp_path / "verified.json").write_text(json.dumps(
        {**VALID, "rule_id": "VERIFIED_RULE", "verification_status": "verified"}))
    assert [r.rule_id for r in RuleLoader(tmp_path).load()] == ["VERIFIED_RULE"]
    assert len(RuleLoader(tmp_path, strict=False).load()) == 2


# --- evaluator --------------------------------------------------------------------------------

def test_rule_fires_when_clause_missing():
    [f] = RuleEvaluator([rule()]).evaluate(NDA_NO_GOVERNING_LAW, "nda")
    assert f.rule_applied == "NDA_GOVERNING_LAW_MISSING@1"
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


# --- versions ---------------------------------------------------------------------------------

def write_rules(directory, **files):
    for name, changes in files.items():
        (directory / f"{name}.json").write_text(json.dumps({**VALID, **changes}))


@pytest.mark.parametrize("change", [
    {"version": 0},
    {"version": "1"},
    {"version": 1.5},
    {"version": True},
    {"effective_to": "2023-12-31"},                      # before effective_from
    {"superseded_by": "lowercase"},
    {"superseded_by": "NDA_GOVERNING_LAW_MISSING@1"},    # itself
])
def test_bad_version_fields_rejected(change):
    with pytest.raises(RuleError):
        rule(**change)


def test_missing_version_rejected_with_the_file_name(tmp_path):
    (tmp_path / "no_version.json").write_text(json.dumps({k: v for k, v in VALID.items() if k != "version"}))
    with pytest.raises(RuleError, match=r"no_version\.json: version: Field required"):
        RuleLoader(tmp_path, strict=False).load()


def test_shipped_rules_are_all_version_1():
    assert {r.version for r in RuleLoader(RULES_DIR, strict=False).load_all()} == {1}


def test_version_in_force_is_picked_by_date(tmp_path):
    write_rules(tmp_path, v1={"version": 1, "effective_to": "2025-12-31"},
                v2={"version": 2, "effective_from": "2026-01-01", "effective_to": "2026-06-30"})

    def version_on(day):
        return [r.version for r in RuleLoader(tmp_path, strict=False, on=day).load()]

    assert version_on(date(2023, 12, 31)) == []         # before v1
    assert version_on(date(2025, 12, 31)) == [1]        # v1's last day (effective_to is inclusive)
    assert version_on(date(2026, 1, 1)) == [2]
    assert version_on(date(2026, 7, 1)) == []           # after v2 ended


def test_strict_does_not_fall_back_to_an_older_verified_version(tmp_path):
    write_rules(tmp_path, v1={"version": 1, "effective_to": "2025-12-31", "verification_status": "verified"},
                v2={"version": 2, "effective_from": "2026-01-01"})
    assert RuleLoader(tmp_path, on=date(2026, 3, 1)).load() == []
    assert [r.version for r in RuleLoader(tmp_path, on=date(2025, 3, 1)).load()] == [1]


@pytest.mark.parametrize("v1, v2", [
    ({}, {"effective_from": "2026-01-01"}),                                   # v1 is open-ended
    ({"effective_to": "2026-01-01"}, {"effective_from": "2026-01-01"}),       # one shared day
    ({"effective_to": "2026-12-31"}, {"effective_from": "2025-01-01", "effective_to": "2025-06-30"}),  # v2 inside v1
])
def test_overlapping_versions_rejected_naming_the_file(tmp_path, v1, v2):
    write_rules(tmp_path, a_v1={"version": 1, **v1}, b_v2={"version": 2, **v2})
    with pytest.raises(RuleError, match=r"b_v2\.json: NDA_GOVERNING_LAW_MISSING@2 .* overlap .*a_v1\.json"):
        RuleLoader(tmp_path, strict=False).load()


def test_same_version_twice_rejected(tmp_path):
    write_rules(tmp_path, a={"effective_to": "2024-12-31"}, b={"effective_from": "2025-01-01"})
    with pytest.raises(RuleError, match=r"b\.json: duplicate rule_id NDA_GOVERNING_LAW_MISSING version 1"):
        RuleLoader(tmp_path, strict=False).load()


def test_superseded_by_must_name_a_known_rule(tmp_path):
    write_rules(tmp_path, old={"rule_id": "OLD_RULE", "superseded_by": "NDA_GOVERNING_LAW_MISSING@1"}, new={})
    assert len(RuleLoader(tmp_path, strict=False).load()) == 2
    write_rules(tmp_path, old={"rule_id": "OLD_RULE", "superseded_by": "NDA_GOVERNING_LAW_MISSING@2"})
    with pytest.raises(RuleError, match=r"old\.json: superseded_by names unknown rule"):
        RuleLoader(tmp_path, strict=False).load()


def test_finding_carries_the_rule_version():
    [f] = RuleEvaluator([rule(version=3)]).evaluate(NDA_NO_GOVERNING_LAW, "nda")
    assert f.rule_applied == "NDA_GOVERNING_LAW_MISSING@3"
    assert f.to_insert_row(uuid4(), uuid4())["rule_applied"] == "NDA_GOVERNING_LAW_MISSING@3"


@pytest.fixture
def rules_dir(monkeypatch, tmp_path):
    """run_review reads its rules from tmp_path for this test."""
    monkeypatch.setattr(api, "RULES_DIR", tmp_path)
    api._rules.cache_clear()
    yield tmp_path
    api._rules.cache_clear()


def test_run_review_uses_the_version_in_force_on_the_date(rules_dir):
    write_rules(rules_dir, v1={"version": 1, "effective_to": "2025-12-31"},
                v2={"version": 2, "effective_from": "2026-01-01"})
    assert demo_on(date(2025, 6, 1)) == ["NDA_GOVERNING_LAW_MISSING@1"]
    assert demo_on(date(2026, 6, 1)) == ["NDA_GOVERNING_LAW_MISSING@2"]


# --- evaluation date --------------------------------------------------------------------------

class _Clock(datetime):
    """datetime whose now() is 2026-10-27 20:00 UTC: already 28 October in India (01:30 IST)."""
    @classmethod
    def now(cls, tz=None):
        return datetime(2026, 10, 27, 20, 0, tzinfo=timezone.utc).astimezone(tz)


def test_today_is_the_indian_date_not_the_server_date(monkeypatch):
    monkeypatch.setattr(schema, "datetime", _Clock)
    assert today_in_india() == date(2026, 10, 28)
    assert api.evaluation_date() == date(2026, 10, 28)


def test_evaluation_date_prefers_on_then_effective_date_then_today(monkeypatch):
    monkeypatch.setattr(schema, "datetime", _Clock)
    assert api.evaluation_date(effective_date=date(2025, 3, 1)) == date(2025, 3, 1)
    assert api.evaluation_date(on=date(2026, 1, 5), effective_date=date(2025, 3, 1)) == date(2026, 1, 5)


def test_run_review_applies_the_contracts_effective_date(rules_dir):
    write_rules(rules_dir, v1={"version": 1, "effective_to": "2025-12-31"},
                v2={"version": 2, "effective_from": "2026-01-01"})
    result = outcome(NDA_NO_GOVERNING_LAW, strict=False, effective_date=date(2025, 6, 1))
    assert result.evaluation_date == date(2025, 6, 1)
    assert [f.rule_applied for f in result.findings] == ["NDA_GOVERNING_LAW_MISSING@1"]


# --- gaps and skipped rules -------------------------------------------------------------------

def test_a_date_between_two_versions_is_a_gap_error(tmp_path):
    write_rules(tmp_path, v1={"version": 1, "effective_to": "2025-06-30"},
                v2={"version": 2, "effective_from": "2026-01-01"})
    with pytest.raises(RuleGapError, match=r"NDA_GOVERNING_LAW_MISSING: no version in force on 2025-09-01: "
                                           r"NDA_GOVERNING_LAW_MISSING@1 ends 2025-06-30 and "
                                           r"NDA_GOVERNING_LAW_MISSING@2 starts 2026-01-01"):
        RuleLoader(tmp_path, strict=False, on=date(2025, 9, 1)).load()
    # Either side of the gap is fine.
    assert [r.version for r in RuleLoader(tmp_path, strict=False, on=date(2025, 6, 30)).load()] == [1]
    assert [r.version for r in RuleLoader(tmp_path, strict=False, on=date(2026, 1, 1)).load()] == [2]


def test_shipped_rule_files_have_no_gaps():
    # Fails the moment a rules edit leaves a day between one version's effective_to and the next's start.
    assert RuleLoader(RULES_DIR, strict=False).gaps() == []


def test_gap_check_finds_a_gap_whatever_the_date(tmp_path):
    write_rules(tmp_path, v1={"version": 1, "effective_to": "2025-06-30"},
                v2={"version": 2, "effective_from": "2025-07-01", "effective_to": "2025-12-31"},
                v3={"version": 3, "effective_from": "2026-02-01"})
    assert RuleLoader(tmp_path, strict=False).gaps() == [
        "NDA_GOVERNING_LAW_MISSING: NDA_GOVERNING_LAW_MISSING@2 ends 2025-12-31 but "
        "NDA_GOVERNING_LAW_MISSING@3 starts 2026-02-01"]


def test_a_gap_error_reaches_the_log(rules_dir, caplog):
    write_rules(rules_dir, v1={"version": 1, "effective_to": "2025-06-30"},
                v2={"version": 2, "effective_from": "2026-01-01"})
    with caplog.at_level("ERROR", logger="app.rules.api"), pytest.raises(RuleGapError):
        review(NDA_NO_GOVERNING_LAW, on=date(2025, 9, 1))
    [line] = [r.getMessage() for r in caplog.records if r.name == "app.rules.api"]
    assert line.startswith("rules review refused: NDA_GOVERNING_LAW_MISSING: no version in force on 2025-09-01")


def test_reviews_endpoint_reports_a_gap_loudly(client, logged_in, rules_dir):
    write_rules(rules_dir, v1={"version": 1, "effective_to": "2025-06-30"},
                v2={"version": 2, "effective_from": "2026-01-01"})
    r = client.post("/reviews?strict=false", json={"contract_text": NDA_NO_GOVERNING_LAW,
                                                   "contract_type_id": "nda", "effective_date": "2025-09-01"})
    assert r.status_code == 500
    assert "NDA_GOVERNING_LAW_MISSING: no version in force on 2025-09-01" in r.json()["detail"]


def skips(result):
    return [(s.rule_id, s.version, s.reason) for s in result.skipped_rules.rules]


def test_a_date_before_the_first_version_is_skipped_and_recorded(rules_dir):
    write_rules(rules_dir, v1={"version": 1, "effective_from": "2026-01-01"})
    result = outcome(NDA_NO_GOVERNING_LAW, strict=False, on=date(2025, 6, 1))
    assert result.findings == [f for f in result.findings if f.layer is Layer.COMPLETENESS]
    assert skips(result) == [("NDA_GOVERNING_LAW_MISSING", 1, SkipReason.NOT_YET_IN_FORCE)]
    assert result.skipped_rules.count == 1


def test_a_date_after_the_last_version_is_skipped_and_recorded(rules_dir):
    write_rules(rules_dir, v1={"version": 1, "effective_to": "2025-12-31"})
    assert skips(outcome(NDA_NO_GOVERNING_LAW, strict=False, on=date(2026, 6, 1))) == [
        ("NDA_GOVERNING_LAW_MISSING", 1, SkipReason.NO_LONGER_IN_FORCE)]


def test_strict_mode_records_the_unverified_current_version(rules_dir):
    write_rules(rules_dir, v1={"version": 1, "effective_to": "2025-12-31", "verification_status": "verified"},
                v2={"version": 2, "effective_from": "2026-01-01"})
    result = outcome(NDA_NO_GOVERNING_LAW, on=date(2026, 6, 1))
    assert result.findings == []
    assert ("NDA_GOVERNING_LAW_MISSING", 2, SkipReason.UNVERIFIED_IN_STRICT_MODE) in skips(result)
    # The unverified completeness checks are listed too, unversioned.
    assert ("NDA_TERM_MISSING", None, SkipReason.UNVERIFIED_IN_STRICT_MODE) in skips(result)


def test_a_rule_for_another_contract_type_is_recorded_as_not_applicable(rules_dir):
    write_rules(rules_dir, sha={"rule_id": "SHA_ONLY", "applies_to": ["sha"], "verification_status": "verified"})
    assert skips(outcome(NDA_NO_GOVERNING_LAW))[0] == ("SHA_ONLY", 1, SkipReason.NOT_APPLICABLE_TO_CONTRACT_TYPE)


def test_one_log_line_per_review_with_counts_and_no_contract_text(caplog):
    with caplog.at_level("INFO", logger="app.rules.api"):
        review(NDA_WITH_RESTRAINT)
    [line] = [r.getMessage() for r in caplog.records if r.name == "app.rules.api"]
    # 5 NDA rule files + 8 completeness checks unverified; the 2 MSMED rules don't apply to an NDA.
    assert "strict=True" in line and "findings=0" in line and "skipped=15" in line
    assert "not_applicable_to_contract_type=2" in line and "unverified_in_strict_mode=13" in line
    assert "Non-Compete" not in line and "Confidential" not in line


def demo_on(day):
    return [f.rule_applied for f in review(NDA_NO_GOVERNING_LAW, strict=False, on=day)]


# --- run_review -------------------------------------------------------------------------------

def demo(text, contract_type="nda"):
    return review(text, contract_type, strict=False)


def test_run_review_is_strict_by_default():
    # Every shipped rule and the NDA completeness config are unverified, so the default returns nothing,
    # even for a bare page that misses every required clause.
    assert review("A bare page.") == []
    assert review(NDA_WITH_RESTRAINT) == []
    assert review("A bare page.", strict=True) == []


def test_run_review_strict_runs_verified_rules(monkeypatch):
    verified = rule(severity="high", verification_status="verified")
    monkeypatch.setattr(api, "_rules", lambda strict, on, contract_type: RuleSelection(rules=(verified,), skipped=()))
    findings = review(NDA_NO_GOVERNING_LAW)
    assert [(f.rule_applied, f.severity, f.verification_status) for f in findings] == [
        ("NDA_GOVERNING_LAW_MISSING@1", Severity.HIGH, VerificationStatus.VERIFIED)]


def test_run_review_demo_returns_unverified_findings_marked_unverified():
    findings = demo(NDA_NO_GOVERNING_LAW)
    assert [f.rule_applied for f in findings] == ["NDA_GOVERNING_LAW_MISSING@1"]
    assert {f.verification_status for f in demo("A bare page.")} == {VerificationStatus.UNVERIFIED}
    assert "ICA_S27_RESTRAINT_OF_TRADE@1" in [f.rule_applied for f in demo(NDA_WITH_RESTRAINT)]


def test_run_review_reports_a_missing_clause_once():
    # The rule file and the completeness checker both cover governing law; only one finding comes back.
    ids = [base_rule_id(f.rule_applied) for f in demo(NDA_NO_GOVERNING_LAW)]
    assert ids.count("NDA_GOVERNING_LAW_MISSING") == 1


def test_run_review_clean_nda_returns_empty_list():
    assert demo(CLEAN_NDA) == []


def test_run_review_sorted_by_severity():
    findings = demo("A bare page.")
    order = ["critical", "high", "medium", "low"]
    assert [order.index(f.severity.value) for f in findings] == sorted(order.index(f.severity.value) for f in findings)


def test_review_finding_is_not_a_findings_column():
    f = demo(NDA_NO_GOVERNING_LAW)[0]
    assert "verification_status" not in f.to_insert_row(uuid4(), uuid4())


@pytest.fixture
def logged_in():
    from app.main import app
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(id="u", email=None, role="startup_user", org_id=None)
    yield
    app.dependency_overrides.clear()


def post_review(client, text, query=""):
    return client.post(f"/reviews{query}", json={"contract_text": text, "contract_type_id": "nda"})


def test_reviews_endpoint_strict_by_default_with_no_verified_rules(client, logged_in):
    r = post_review(client, NDA_NO_GOVERNING_LAW)
    assert r.status_code == 200
    body = r.json()
    assert (body["strict_mode"], body["status"], body["notice"], body["findings"]) == (
        True, "no_verified_rules_matched", None, [])
    # Not "nothing found": the 5 NDA rule files and the 8 completeness checks were skipped as unverified,
    # and the 2 MSMED rules as not applying to an NDA.
    reasons = [s["reason"] for s in body["skipped_rules"]["rules"]]
    assert body["skipped_rules"]["count"] == 15 == len(reasons)
    assert (reasons.count("unverified_in_strict_mode"), reasons.count("not_applicable_to_contract_type")) == (13, 2)
    assert body["evaluation_date"] == today_in_india().isoformat()
    assert client.post("/reviews", json={"contract_text": "", "contract_type_id": "nda"}).status_code == 422


def test_reviews_endpoint_strict_returns_verified_findings(client, logged_in, monkeypatch):
    monkeypatch.setattr(api, "_rules", lambda strict, on, contract_type: RuleSelection(
        rules=(rule(verification_status="verified"),), skipped=()))
    body = post_review(client, NDA_NO_GOVERNING_LAW).json()
    assert (body["strict_mode"], body["status"], body["notice"]) == (True, "ok", None)
    assert [(f["rule_applied"], f["verification_status"]) for f in body["findings"]] == [
        ("NDA_GOVERNING_LAW_MISSING@1", "verified")]


def test_reviews_endpoint_demo_mode_is_labelled(client, logged_in):
    r = post_review(client, NDA_NO_GOVERNING_LAW, "?strict=false")
    assert r.status_code == 200
    body = r.json()
    assert (body["strict_mode"], body["status"], body["notice"]) == (False, "demo_includes_unverified", api.DEMO_NOTICE)
    assert [(f["rule_applied"], f["verification_status"]) for f in body["findings"]] == [
        ("NDA_GOVERNING_LAW_MISSING@1", "unverified")]


def test_reviews_endpoint_requires_login(client):
    r = client.post("/reviews", json={"contract_text": "x", "contract_type_id": "nda"})
    assert r.status_code in (401, 403)
