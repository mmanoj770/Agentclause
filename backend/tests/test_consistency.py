"""R6 Layer 3 cross-clause consistency: the same fact stated differently in two clauses."""
import pytest
from pydantic import ValidationError

from app.agents.citation_gate import DocumentContext, StubFixtureCorpus, check_finding
from app.pipeline.consistency import CONFIG_PATH, ConsistencyConfig, extract_facts, load_config, run_consistency
from app.schemas.finding import CitationType, Finding, Layer, Severity
from app.schemas.normalized_document import NormalizedDocument

TEST_CONFIG = {"status": "TEST", "severity": {"governing_law": "high", "jurisdiction": "high",
                                              "payment_period": "medium", "termination_notice": "medium",
                                              "agreement_term": "medium"}}
HEAD = ('SUPPLY AGREEMENT\n\nThis Agreement is between Elm Example Components Private Limited (the "Supplier") '
        'and Fern Example Grid Systems Private Limited (the "Buyer").\n\n')
CONSISTENT = HEAD + """1. Payment. The Buyer shall pay each invoice within thirty (30) days of acceptance.

2. Term. This Agreement shall remain in force for a period of two years.

3. Termination. Either party may terminate this Agreement on thirty days' written notice.

4. Governing Law. This Agreement is governed by the laws of India, and the courts at Pune have exclusive jurisdiction.

5. Disputes. Any dispute shall be heard by the courts at Pune, which have exclusive jurisdiction.
"""


def doc(text: str) -> NormalizedDocument:
    return NormalizedDocument(parties=["Elm Example Components Private Limited", "Fern Example Grid Systems Private Limited"],
                              document_type="vendor_supplier", clauses=["other"], full_text=text)


def findings(text: str, **kw):
    return run_consistency(doc(text), config=kw.pop("config", ConsistencyConfig.model_validate(TEST_CONFIG))).findings


def summary(text: str):
    return [(f.rule_applied, f.citation) for f in findings(text)]


def test_a_consistent_contract_has_no_findings():
    assert findings(CONSISTENT) == []
    assert {f.topic for f in extract_facts(CONSISTENT)} == {"payment_period", "agreement_term", "termination_notice",
                                                           "governing_law", "jurisdiction"}


@pytest.mark.parametrize("old, new, rule, cited", [
    ("courts at Pune, which", "courts at Mumbai, which", "R6_CONFLICT_JURISDICTION", "Internal: Clause 4 vs Clause 5"),
    ("5. Disputes. Any dispute shall be heard by the courts at Pune, which have exclusive jurisdiction.",
     "5. Disputes. This Agreement shall be construed in accordance with the laws of Singapore.",
     "R6_CONFLICT_GOVERNING_LAW", "Internal: Clause 4 vs Clause 5"),
    ("5. Disputes.", "5. Disputes. The Buyer shall pay any disputed amount within sixty (60) days of settlement.",
     "R6_CONFLICT_PAYMENT_PERIOD", "Internal: Clause 1 vs Clause 5"),
    ("5. Disputes.", "5. Disputes. The Supplier may terminate this Agreement on 90 days' written notice.",
     "R6_CONFLICT_TERMINATION_NOTICE", "Internal: Clause 3 vs Clause 5"),
    ("5. Disputes.", "5. Disputes. This Agreement shall remain in force for 18 months.",
     "R6_CONFLICT_AGREEMENT_TERM", "Internal: Clause 2 vs Clause 5"),
])
def test_a_conflict_between_two_clauses_is_a_finding(old, new, rule, cited):
    assert summary(CONSISTENT.replace(old, new)) == [(rule, cited)]


def test_the_finding_is_a_valid_layer_3_finding():
    [f] = findings(CONSISTENT.replace("courts at Pune, which", "courts at Mumbai, which"))
    assert (f.layer, f.citation_type, f.severity, f.clause_reference) == (
        Layer.CONSISTENCY, CitationType.INTERNAL_BASELINE, Severity.HIGH, "Clause 4")
    assert f.description == "Clause 4 and Clause 5 give different courts with jurisdiction: Pune and Mumbai."
    Finding.model_validate(f.model_dump())


def test_the_same_value_written_differently_is_not_a_conflict():
    # "two years" in clause 2 and "24 months" elsewhere are the same term.
    assert findings(CONSISTENT.replace("5. Disputes.", "5. Disputes. This Agreement shall remain in force for 24 months.")) == []


def test_two_values_in_one_clause_are_not_cited(caplog):
    text = CONSISTENT.replace("2. Term. This Agreement shall remain in force for a period of two years.",
                              "2. Term. This Agreement shall remain in force for two years. "
                              "This Agreement shall remain in force for three years.")
    with caplog.at_level("INFO", logger="app.pipeline.consistency"):
        assert findings(text) == []
    assert "same_clause_conflicts=1" in caplog.text


def test_each_new_value_is_paired_with_the_first_clause_once():
    text = CONSISTENT.replace("5. Disputes.", "5. Disputes. This Agreement shall remain in force for 18 months.") + \
        "\n6. Renewal. This Agreement shall remain in force for 18 months.\n7. Extra. This Agreement shall remain in force for 4 years.\n"
    assert summary(text) == [("R6_CONFLICT_AGREEMENT_TERM", "Internal: Clause 2 vs Clause 5"),
                             ("R6_CONFLICT_AGREEMENT_TERM", "Internal: Clause 2 vs Clause 7")]


def test_late_payment_interest_is_not_a_payment_period():
    text = CONSISTENT.replace("5. Disputes.", "5. Disputes. Interest is payable on amounts unpaid after 90 days.")
    assert findings(text) == []


def test_the_shipped_config_is_a_placeholder_and_caps_findings_at_low():
    shipped = load_config(CONFIG_PATH)
    assert shipped.status == "PLACEHOLDER" and "lawyer" in shipped.note
    [f] = findings(CONSISTENT.replace("courts at Pune, which", "courts at Mumbai, which"), config=shipped)
    assert f.severity is Severity.LOW


@pytest.mark.parametrize("severity", [{"governing_law": "high"}, {**TEST_CONFIG["severity"], "extra": "low"},
                                      {**TEST_CONFIG["severity"], "jurisdiction": "info"}])
def test_a_bad_config_is_rejected(severity):
    with pytest.raises(ValidationError):
        ConsistencyConfig.model_validate({**TEST_CONFIG, "severity": severity})


def test_no_contract_text_reaches_the_log(caplog):
    with caplog.at_level("INFO", logger="app.pipeline.consistency"):
        findings(CONSISTENT.replace("courts at Pune, which", "courts at Mumbai, which"))
    assert "consistency:" in caplog.text and "Mumbai" not in caplog.text and "Elm" not in caplog.text


def test_findings_pass_the_gate_with_a_manifest_and_are_blocked_without_one():
    [f] = findings(CONSISTENT.replace("courts at Pune, which", "courts at Mumbai, which"))
    with_manifest = DocumentContext("vendor_supplier", frozenset({"1", "2", "3", "4", "5"}))
    assert check_finding(f, StubFixtureCorpus(), with_manifest).allowed
    blocked = check_finding(f, StubFixtureCorpus(), DocumentContext("vendor_supplier"))
    assert not blocked.allowed and blocked.reason.value == "no_clause_manifest"
