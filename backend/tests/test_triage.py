"""R9 risk triage: tiers from a weighted severity score, read from config/triage.json."""
import json

import pytest
from pydantic import ValidationError

from app.pipeline import triage as triage_module
from app.pipeline.triage import CONFIG_PATH, TIERS, load_config, save_triage, triage
from app.schemas.finding import CitationType, Finding, Layer, Severity

TEST_CONFIG = {
    "status": "TEST",
    "severity_weights": {"critical": 5.0, "high": 3.0, "medium": 1.0, "low": 0.5},
    "asymmetry_weight": 2.0,
    "thresholds": {"enhanced": 4.0, "senior_counsel": 10.0},
}


def config(**changes):
    return triage_module.TriageConfig.model_validate({**TEST_CONFIG, **changes})


def finding(severity: str, rule: str = "TEST_RULE") -> Finding:
    return Finding(layer=Layer.STATUTORY, severity=severity, clause_reference="Clause 1", description="d",
                   rule_applied=rule, remedy_suggested="r", citation="Indian Contract Act, 1872, s. 27",
                   citation_type=CitationType.STATUTORY)


def tier_of(*severities, **kw):
    return triage([finding(s, f"RULE_{i}") for i, s in enumerate(severities)], config=config(), **kw)


# --- tiers ------------------------------------------------------------------------------------

def test_empty_findings_are_standard():
    result = triage([], config=config())
    assert (result["review_tier"], result["score"]) == ("standard", 0)
    assert result["reasons"] == ["score 0 is below the enhanced threshold 4"]


@pytest.mark.parametrize("severities, score, tier", [
    (("high", "low"), 3.5, "standard"),                     # just below enhanced
    (("high", "medium"), 4.0, "enhanced"),                  # exactly on the enhanced threshold
    (("high", "high", "high", "low"), 9.5, "enhanced"),     # just below senior_counsel
    (("high", "high", "high", "medium"), 10.0, "senior_counsel"),   # exactly on it
    (("critical", "critical", "high"), 13.0, "senior_counsel"),
])
def test_each_tier_boundary(severities, score, tier):
    result = tier_of(*severities)
    assert (result["score"], result["review_tier"]) == (score, tier)


def test_a_critical_finding_gives_at_least_enhanced():
    cheap_critical = config(severity_weights={**TEST_CONFIG["severity_weights"], "critical": 1.0})
    result = triage([finding("critical", "ICA_S27_RESTRAINT_OF_TRADE")], config=cheap_critical)
    assert (result["score"], result["review_tier"]) == (1.0, "enhanced")      # score alone says standard
    assert result["reasons"][-1] == "critical finding(s) ICA_S27_RESTRAINT_OF_TRADE: at least enhanced"


def test_a_critical_finding_never_lowers_the_tier():
    assert tier_of("critical", "critical")["review_tier"] == "senior_counsel"


def test_the_asymmetry_score_is_weighted_into_the_total():
    result = tier_of("medium", asymmetry_score=1.5)            # 1 + 2.0 x 1.5
    assert (result["score"], result["review_tier"]) == (4.0, "enhanced")
    assert "risk asymmetry 1.5 x 2: +3" in result["reasons"]


def test_reasons_name_the_findings_that_drove_the_tier_largest_first():
    result = triage([finding("low", "B_RULE"), finding("high", "A_RULE"), finding("medium", "C_RULE")],
                    config=config(severity_weights={**TEST_CONFIG["severity_weights"], "low": 0.0}))
    assert result["reasons"] == ["A_RULE (high): +3", "C_RULE (medium): +1",
                                 "score 4 reaches the enhanced threshold 4"]   # zero-weight low is left out


def test_reasons_carry_no_finding_text():
    text = " ".join(triage([finding("critical")], config=config())["reasons"])
    assert "Clause 1" not in text and " d " not in f" {text} " and "Indian Contract Act" not in text


# --- config -----------------------------------------------------------------------------------

def test_thresholds_and_weights_are_read_from_the_config_file(tmp_path):
    path = tmp_path / "triage.json"
    path.write_text(json.dumps({**TEST_CONFIG, "thresholds": {"enhanced": 1.0, "senior_counsel": 2.0}}))
    strict = load_config(path)
    assert triage([finding("medium")], config=config())["review_tier"] == "standard"
    assert triage([finding("medium")], config=strict)["review_tier"] == "enhanced"
    assert triage([finding("medium"), finding("medium")], config=strict)["review_tier"] == "senior_counsel"


def test_the_shipped_config_is_a_labelled_placeholder_and_is_the_default(monkeypatch):
    shipped = load_config(CONFIG_PATH)
    assert shipped.status == "PLACEHOLDER" and "lawyer" in shipped.note
    triage_module._default_config.cache_clear()
    assert triage([finding("high")]) == triage([finding("high")], config=shipped)


@pytest.mark.parametrize("changes", [
    {"thresholds": {"enhanced": 5.0, "senior_counsel": 5.0}},     # senior must be above enhanced
    {"thresholds": {"enhanced": 0, "senior_counsel": 5.0}},
    {"severity_weights": {**TEST_CONFIG["severity_weights"], "high": -1}},
    {"severity_weights": {"critical": 5, "high": 3, "medium": 1}},  # a severity missing
    {"asymmetry_weight": -1},
    {"tiers": ["x"]},                                              # unknown key
    {"status": ""},
])
def test_a_bad_config_is_rejected(changes):
    with pytest.raises(ValidationError):
        config(**changes)


# --- storing it -------------------------------------------------------------------------------

class FakeConn:
    def __init__(self):
        self.calls = []

    def execute(self, sql, params=()):
        self.calls.append((" ".join(sql.split()), params))


def test_save_triage_sets_the_tier_and_audits_the_score_and_reasons():
    conn, result = FakeConn(), tier_of("high", "medium")
    save_triage(conn, "doc-1", result, config=config())
    (update, update_params), (insert, insert_params) = conn.calls
    assert update == "update documents set triage_tier = %s where id = %s" and update_params == ("enhanced", "doc-1")
    assert insert.startswith("insert into audit_logs")
    document_id, actor_id, actor_role, action, details = insert_params
    assert (document_id, actor_id, actor_role, action) == ("doc-1", None, "system", "triage_assigned")
    assert details.obj == {"review_tier": "enhanced", "score": 4.0, "reasons": result["reasons"],
                           "config_status": "TEST"}


def test_save_triage_refuses_a_tier_the_table_would_reject():
    with pytest.raises(ValueError):
        save_triage(FakeConn(), "doc-1", {"review_tier": "urgent", "score": 1.0, "reasons": []}, config=config())


def test_tiers_match_the_documents_triage_tier_check():
    # migration 04: check (triage_tier in ('standard', 'enhanced', 'senior_counsel'))
    assert TIERS == ("standard", "enhanced", "senior_counsel")
