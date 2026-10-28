"""R5 seed rules (ICA ss.28 and 74, MSMED Act ss.15 and 16) and the number_after_keyword_exceeds condition.

The seed rules are test fixtures written from statute text by a non-lawyer: all unverified, so strict
mode must never return them.
"""
import asyncio

import pytest

from app.agents.citation_gate import StubFixtureCorpus, check_finding
from app.rules.api import RULES_DIR, run_review
from app.rules.engine import RuleEvaluator, number_after_keyword_exceeds
from app.rules.schema import RuleError, RuleLoader, RuleValidator, SkipReason, parse_condition
from app.schemas.finding import CitationType, Layer, Severity

SEED = ("ICA_S28_RESTRAINT_OF_LEGAL_PROCEEDINGS", "ICA_S74_PENALTY_OR_LIQUIDATED_DAMAGES",
        "MSMED_S15_PAYMENT_BEYOND_45_DAYS", "MSMED_S16_INTEREST_WAIVER")
# The Layer 5 stub corpus has no ICA s.28 entry yet. Remove this once the corpus owner adds it.
KNOWN_NOT_IN_CORPUS = {"ICA_S28_RESTRAINT_OF_LEGAL_PROCEEDINGS"}

# (rule_id, contract type, a clause that fires, a clause that doesn't)
CASES = [
    ("ICA_S28_RESTRAINT_OF_LEGAL_PROCEEDINGS", "msa",
     "12. Claims. Any claim arising under this Agreement must be brought within three months of the event.",
     "12. Arbitration. Any dispute shall be referred to arbitration under the Arbitration and Conciliation "
     "Act, 1996, seated at Mumbai. The award shall be final and binding."),
    ("ICA_S74_PENALTY_OR_LIQUIDATED_DAMAGES", "vendor_supplier",
     "9. Delay. The Supplier shall pay liquidated damages of 1% of the order value per week of delay.",
     "9. Delay. The Supplier is liable for the loss the Buyer proves it suffered because of the delay."),
    ("MSMED_S15_PAYMENT_BEYOND_45_DAYS", "vendor_supplier",
     "5. Payment. The Buyer shall pay each invoice within sixty (60) days of acceptance of the goods.",
     "5. Payment. The Buyer shall pay each invoice within thirty (30) days of acceptance of the goods."),
    ("MSMED_S16_INTEREST_WAIVER", "sla",
     "6. Late payment. No interest shall be payable on any delayed payment.",
     "6. Late payment. Interest on delayed payments is payable as provided in section 16 of the Micro, "
     "Small and Medium Enterprises Development Act, 2006."),
]
EVERY_SEED_CLAUSE = "VENDOR AGREEMENT\n\n" + "\n\n".join(fires for _, _, fires, _ in CASES)


def seed_rule(rule_id):
    [rule] = [r for r in RuleLoader(RULES_DIR, strict=False).load_all() if r.rule_id == rule_id]
    return rule


def evaluate(rule_id, text, contract_type):
    return RuleEvaluator([seed_rule(rule_id)]).evaluate(text, contract_type)


# --- each seed rule ---------------------------------------------------------------------------

@pytest.mark.parametrize("rule_id, contract_type, fires, _", CASES, ids=[c[0] for c in CASES])
def test_seed_rule_fires(rule_id, contract_type, fires, _):
    [f] = evaluate(rule_id, fires, contract_type)
    assert f.rule_applied == f"{rule_id}@1"
    assert f.layer is Layer.STATUTORY and f.citation_type is CitationType.STATUTORY
    assert f.severity is Severity.LOW          # unverified: capped at LOW
    assert f.clause_reference.startswith("Clause ")


@pytest.mark.parametrize("rule_id, contract_type, _, clean", CASES, ids=[c[0] for c in CASES])
def test_seed_rule_does_not_fire(rule_id, contract_type, _, clean):
    assert evaluate(rule_id, clean, contract_type) == []


@pytest.mark.parametrize("rule_id", SEED)
def test_seed_rule_is_an_unverified_statutory_fixture(rule_id):
    rule = seed_rule(rule_id)
    assert not rule.verified, f"{rule_id} must stay unverified until a lawyer signs it off"
    assert rule.citation_type is CitationType.STATUTORY and rule.basis and rule.version == 1


def test_seed_citations_use_the_repo_statute_format():
    citations = {r: seed_rule(r).citation for r in SEED}
    assert citations == {
        "ICA_S28_RESTRAINT_OF_LEGAL_PROCEEDINGS": "Indian Contract Act, 1872, s. 28",
        "ICA_S74_PENALTY_OR_LIQUIDATED_DAMAGES": "Indian Contract Act, 1872, s. 74",
        "MSMED_S15_PAYMENT_BEYOND_45_DAYS": "Micro, Small and Medium Enterprises Development Act, 2006, s. 15",
        "MSMED_S16_INTEREST_WAIVER": "Micro, Small and Medium Enterprises Development Act, 2006, s. 16",
    }


@pytest.mark.parametrize("rule_id, contract_type, fires, _", CASES, ids=[c[0] for c in CASES])
def test_seed_citations_pass_the_layer_5_gate(rule_id, contract_type, fires, _):
    [f] = evaluate(rule_id, fires, contract_type)
    decision = check_finding(f, StubFixtureCorpus())
    if rule_id in KNOWN_NOT_IN_CORPUS:
        assert not decision.allowed and decision.reason.value == "not_in_corpus"
    else:
        assert decision.allowed, decision.detail


def test_msmed_rules_apply_to_vendor_and_service_contracts_only():
    for rule_id in ("MSMED_S15_PAYMENT_BEYOND_45_DAYS", "MSMED_S16_INTEREST_WAIVER"):
        assert seed_rule(rule_id).applies_to == ["msa", "sla", "vendor_supplier"]
    assert evaluate("MSMED_S15_PAYMENT_BEYOND_45_DAYS", CASES[2][2], "nda") == []


# --- strict mode ------------------------------------------------------------------------------

def test_strict_mode_returns_none_of_the_seed_rules():
    demo = asyncio.run(run_review(EVERY_SEED_CLAUSE, "vendor_supplier", strict=False))
    assert {f.rule_applied for f in demo.findings} >= {f"{r}@1" for r in SEED}   # they do fire in demo mode

    for strict in (asyncio.run(run_review(EVERY_SEED_CLAUSE, "vendor_supplier")),
                   asyncio.run(run_review(EVERY_SEED_CLAUSE, "vendor_supplier", strict=True))):
        assert not any(f.rule_applied.split("@")[0] in SEED for f in strict.findings)
        skipped = {(s.rule_id, s.reason) for s in strict.skipped_rules.rules}
        assert {(r, SkipReason.UNVERIFIED_IN_STRICT_MODE) for r in SEED} <= skipped


# --- number_after_keyword_exceeds -------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "The Buyer shall pay within 60 days.",
    "Payment is due within sixty (60) days of the invoice.",
    "Amounts are payable 46 days after acceptance.",
    "The Buyer shall pay Rs. 5,000 within 90 days.",        # "Rs." does not end the sentence
    "Payment within 60 business days of acceptance.",       # up to two words before the unit
    "Payment: 30 days for goods and 50 days for services",  # any number over the limit in the sentence
])
def test_number_after_keyword_fires(text):
    assert number_after_keyword_exceeds(text, "pay", 45, "days") is not None


@pytest.mark.parametrize("text", [
    "The Buyer shall pay within 45 days.",                  # the limit itself is allowed
    "The Buyer shall pay within forty-five (45) days.",
    "Payment is due within sixty days.",                    # numbers in words are not read
    "The Buyer shall pay promptly. The warranty lasts 90 days.",   # another sentence
    "Payment of 60 percent is due on signing.",             # not the unit
    "The warranty lasts 90 days.",                          # no keyword
    "Repay within 60 days.",                                # "pay" must start a word
])
def test_number_after_keyword_does_not_fire(text):
    assert number_after_keyword_exceeds(text, "pay", 45, "days") is None


def test_number_after_keyword_unit_is_singular_or_plural():
    assert number_after_keyword_exceeds("Pay within 50 day.", "pay", 45, "days") is not None
    assert number_after_keyword_exceeds("Pay within 50 days.", "pay", 45, "day") is not None


def test_number_after_keyword_is_case_insensitive_and_reports_the_keyword_that_fired():
    # The heading's PAYMENT has no number in its sentence; the second PAYMENT does.
    text = "Intro.\n\n7. PAYMENT TERMS. PAYMENT within 75 DAYS of acceptance."
    assert number_after_keyword_exceeds(text, "pay", 45, "days") == text.rindex("PAYMENT")


def test_a_semicolon_ends_the_sentence():
    assert number_after_keyword_exceeds("Payment: 30 days for goods; 50 days for services",
                                        "pay", 45, "days") is None


def test_number_after_keyword_condition_parses():
    assert parse_condition("number_after_keyword_exceeds('pay', 45, 'days')") == (
        "number_after_keyword_exceeds", ("pay", 45, "days"))


@pytest.mark.parametrize("condition", [
    "number_after_keyword_exceeds('pay', '45', 'days')",    # limit must be a number
    "number_after_keyword_exceeds('pay', 45.5, 'days')",
    "number_after_keyword_exceeds('pay', True, 'days')",
    "number_after_keyword_exceeds('pay', -1, 'days')",
    "number_after_keyword_exceeds('pay', 45)",               # unit missing
    "number_after_keyword_exceeds('', 45, 'days')",
    "number_after_keyword_exceeds('pay', 45, 'days', 'x')",
    "contains_text('pay', 45)",                               # other conditions stay string-only
])
def test_bad_number_conditions_rejected(condition):
    with pytest.raises(ValueError):
        parse_condition(condition)


def test_bad_number_condition_in_a_rule_file_names_the_problem():
    with pytest.raises(RuleError, match="number_after_keyword_exceeds"):
        RuleValidator.validate({**seed_rule("MSMED_S15_PAYMENT_BEYOND_45_DAYS").model_dump(mode="json"),
                                "condition": "number_after_keyword_exceeds('pay', '45', 'days')"})
