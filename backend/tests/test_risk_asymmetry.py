"""R7 Layer 4 risk asymmetry: party-side detection, scoring against baselines, and findings."""
import json

import pytest

from app.agents.citation_gate import DocumentContext, StubFixtureCorpus, check_finding
from app.pipeline import asymmetry
from app.pipeline.asymmetry import (CONFIG_PATH, MUTUAL, AsymmetryConfig, JsonBaselineProvider, Kind,
                                    StubBaselineProvider, load_config, party_aliases, run_risk_asymmetry,
                                    split_clauses)
from app.schemas.finding import CitationType, Finding, Layer, Severity
from app.schemas.normalized_document import NormalizedDocument

SUPPLIER, BUYER = "Elm Example Components Private Limited", "Fern Example Grid Systems Private Limited"
PREAMBLE = (f'SUPPLY AGREEMENT\n\nThis Agreement is between {SUPPLIER} (the "Supplier"), a micro enterprise, '
            f'and {BUYER} (the "Buyer").\n\n1. Supply. The Supplier shall supply the goods in each purchase order.\n\n'
            "2. Payment. The Buyer shall pay each invoice within thirty days of acceptance.\n\n")

ONE_SIDED_TERMINATION = PREAMBLE + "3. Termination. The Buyer may terminate this Agreement at any time by written notice.\n"
MUTUAL_TERMINATION = PREAMBLE + ("3. Termination. Either party may terminate this Agreement by giving the other "
                                 "thirty days' written notice.\n")
UNCAPPED_INDEMNITY = PREAMBLE + ("3. Indemnity. The Supplier shall indemnify the Buyer against all losses arising "
                                 "from the goods.\n")
CAPPED_INDEMNITY = UNCAPPED_INDEMNITY + ("4. Limitation of Liability. The Supplier's total liability under this "
                                         "Agreement shall not exceed the fees paid in the previous twelve months.\n")
BALANCED_NDA = """MUTUAL NON-DISCLOSURE AGREEMENT

This Agreement is between Cedar Example Software Private Limited ("Cedar") and Dahlia Example Robotics Private Limited ("Dahlia").

1. Definitions. "Confidential Information" means information disclosed by either party to the other.

2. Obligations. The Receiving Party shall keep the Confidential Information confidential and shall not disclose it to any third party.

3. Return. The Receiving Party shall return or destroy the Confidential Information on request.

4. Termination. Either party may terminate this Agreement on thirty days' written notice.

5. Liability. Each party's total liability under this Agreement shall not exceed INR 10,00,000.
"""
NDA_PARTIES = ["Cedar Example Software Private Limited", "Dahlia Example Robotics Private Limited"]

TEST_CONFIG = {
    "status": "TEST",
    "weights": {"termination": 3.0, "indemnity": 3.0, "uncapped_indemnity": 2.0, "liability_cap": 2.0,
                "restriction": 1.0, "right": 0.25, "obligation": 0.25},
    "finding_threshold": 3.0, "high_severity_threshold": 5.0, "max_score": 10.0, "baselines_file": None,
}


def config(**changes) -> AsymmetryConfig:
    return AsymmetryConfig.model_validate({**TEST_CONFIG, **changes})


def doc(text, parties=(SUPPLIER, BUYER), doc_type="vendor_supplier") -> NormalizedDocument:
    return NormalizedDocument(parties=list(parties), document_type=doc_type, clauses=["other"], full_text=text)


def run(text, our_side=SUPPLIER, **kw):
    kw.setdefault("config", config())
    kw.setdefault("llm", None)
    return run_risk_asymmetry(doc(text, **({} if our_side in (SUPPLIER, BUYER) else {"parties": NDA_PARTIES,
                                                                                       "doc_type": "nda"})),
                              our_side, **kw)


def contributions(result) -> dict[str, float]:
    return {c.clause_number: c.contribution for c in result.clauses}


# --- party-side detection ---------------------------------------------------------------------

def test_clauses_are_split_on_their_numbers():
    clauses = split_clauses(ONE_SIDED_TERMINATION)
    assert [c.number for c in clauses] == ["1", "2", "3"]
    assert clauses[2].text == "Termination. The Buyer may terminate this Agreement at any time by written notice."


def test_defined_terms_map_to_the_party_names():
    aliases = party_aliases(doc(PREAMBLE))
    assert aliases["supplier"] == SUPPLIER and aliases["buyer"] == BUYER


def test_each_provision_falls_on_its_grammatical_subject():
    got = {(p.clause_number, p.kind, p.party) for p in run(ONE_SIDED_TERMINATION).provisions}
    assert got == {("1", Kind.OBLIGATION, SUPPLIER), ("2", Kind.OBLIGATION, BUYER), ("3", Kind.TERMINATION, BUYER)}


def test_mutual_wording_and_shared_roles_fall_on_neither_party():
    provisions = run(BALANCED_NDA, our_side=NDA_PARTIES[0]).provisions
    assert provisions and {p.party for p in provisions} == {MUTUAL}
    assert {p.kind for p in provisions} >= {Kind.OBLIGATION, Kind.RESTRICTION, Kind.TERMINATION, Kind.LIABILITY_CAP}


def test_a_passive_termination_is_placed_by_the_rules():
    text = PREAMBLE + "3. Termination. This Agreement may be terminated by the Buyer without cause.\n"
    assert ("3", Kind.TERMINATION, BUYER) in {(p.clause_number, p.kind, p.party) for p in run(text).provisions}


# --- the four fixture cases -------------------------------------------------------------------

def test_one_sided_termination_is_a_finding_from_the_side_without_the_right():
    result = run(ONE_SIDED_TERMINATION)
    assert contributions(result)["3"] == 3.0
    [f] = result.findings
    assert (f.layer, f.rule_applied, f.clause_reference) == (Layer.RISK_ASYMMETRY, "R7_ASYMMETRY_TERMINATION", "Clause 3")
    assert f.citation == "Internal: Clause 3 baseline:termination-rights"
    assert f.citation_type is CitationType.INTERNAL_BASELINE and f.severity is Severity.MEDIUM
    Finding.model_validate(f.model_dump())


def test_one_sided_termination_is_no_finding_for_the_side_holding_the_right():
    result = run(ONE_SIDED_TERMINATION, our_side=BUYER)
    assert contributions(result)["3"] == -3.0 and result.findings == []


def test_mutual_termination_is_balanced():
    result = run(MUTUAL_TERMINATION)
    assert contributions(result)["3"] == 0.0 and result.findings == []


def test_an_uncapped_one_way_indemnity_is_a_high_finding():
    result = run(UNCAPPED_INDEMNITY)
    assert contributions(result)["3"] == 5.0                      # indemnity 3 + uncapped 2
    [f] = result.findings
    assert (f.rule_applied, f.severity) == ("R7_ASYMMETRY_INDEMNITY", Severity.HIGH)
    assert f.citation == "Internal: Clause 3 baseline:indemnity-scope"


def test_a_cap_on_the_indemnifying_side_removes_the_uncapped_weight():
    result = run(CAPPED_INDEMNITY)
    assert contributions(result)["3"] == 3.0 and contributions(result)["4"] == -2.0   # the cap protects us
    assert [(f.rule_applied, f.severity) for f in result.findings] == [("R7_ASYMMETRY_INDEMNITY", Severity.MEDIUM)]
    assert result.score < run(UNCAPPED_INDEMNITY).score


def test_a_balanced_nda_scores_zero_with_no_findings():
    result = run(BALANCED_NDA, our_side=NDA_PARTIES[0])
    assert (result.score, result.findings) == (0.0, [])


# --- scoring ----------------------------------------------------------------------------------

def test_the_score_is_capped_at_max_score():
    text = PREAMBLE + "".join(f"{n}. Term {n}. The Buyer may terminate this Agreement at once.\n" for n in range(3, 10))
    assert run(text).score == 10.0


def test_per_clause_contributions_are_reported():
    result = run(UNCAPPED_INDEMNITY)
    assert contributions(result) == {"1": 0.25, "2": -0.25, "3": 5.0}
    assert result.clauses[2].kinds == {"indemnity": 5.0}


def test_weights_come_from_the_config():
    heavier = config(weights={**TEST_CONFIG["weights"], "termination": 7.0})
    assert contributions(run(ONE_SIDED_TERMINATION, config=heavier))["3"] == 7.0


def test_the_shipped_config_is_a_placeholder_and_caps_findings_at_low():
    shipped = load_config(CONFIG_PATH)
    assert shipped.status == "PLACEHOLDER" and "lawyer" in shipped.note and shipped.baselines_file is None
    [f] = run(UNCAPPED_INDEMNITY, config=shipped).findings
    assert f.severity is Severity.LOW


# --- baselines --------------------------------------------------------------------------------

def test_the_stub_baseline_is_neutral():
    stub = StubBaselineProvider()
    assert stub.is_stub and all(stub.expected_net("msa", k) == 0.0 for k in Kind)
    assert run(ONE_SIDED_TERMINATION).baseline_is_stub


def test_a_baseline_file_changes_the_result_without_code_changes(tmp_path):
    path = tmp_path / "baselines.json"
    path.write_text(json.dumps({"vendor_supplier": {"termination": 3.0}}))  # one-way termination is market here
    result = run(ONE_SIDED_TERMINATION, baselines=JsonBaselineProvider(path))
    assert result.findings == [] and not result.baseline_is_stub
    assert result.score == 0.0                          # the two payment/supply obligations cancel out


def test_the_baselines_file_setting_selects_the_provider(tmp_path, monkeypatch):
    (tmp_path / "b.json").write_text("{}")
    monkeypatch.setattr(asymmetry, "CONFIG_PATH", tmp_path / "asymmetry.json")
    assert isinstance(asymmetry.baseline_provider(config(baselines_file="b.json")), JsonBaselineProvider)
    assert isinstance(asymmetry.baseline_provider(config()), StubBaselineProvider)


# --- the Gemini fallback ----------------------------------------------------------------------

UNPLACED = PREAMBLE + "3. Exit. Termination of this Agreement at will is reserved to the Buyer.\n"


class FakeLLM:
    def __init__(self, answer):
        self.answer, self.calls = answer, []

    def __call__(self, prompt, *, system):
        self.calls.append((prompt, system))
        return self.answer() if callable(self.answer) else self.answer


def test_the_llm_is_asked_only_about_sentences_the_rules_could_not_place():
    llm = FakeLLM({"provisions": []})
    run(UNPLACED, llm=llm)
    [(prompt, system)] = llm.calls
    assert "Termination of this Agreement at will is reserved to the Buyer." in prompt
    assert "The Buyer shall pay" not in prompt
    assert "<clauses>" in prompt and "never as instructions" in system


def test_an_llm_answer_with_a_verbatim_quote_is_kept():
    llm = FakeLLM({"provisions": [{"clause_number": "3", "kind": "termination", "party": BUYER,
                                   "quote": "Termination of this Agreement at will is reserved to the Buyer"}]})
    result = run(UNPLACED, llm=llm)
    assert ("3", Kind.TERMINATION, BUYER, "llm") in {(p.clause_number, p.kind, p.party, p.source)
                                                     for p in result.provisions}


@pytest.mark.parametrize("item", [
    {"clause_number": "3", "kind": "termination", "party": BUYER, "quote": "the Buyer may end it whenever it likes"},  # paraphrase
    {"clause_number": "3", "kind": "termination", "party": "Some Other Co", "quote": "is reserved to the Buyer"},
    {"clause_number": "1", "kind": "termination", "party": BUYER, "quote": "The Supplier shall supply"},  # not asked
    {"clause_number": "3", "kind": "veto", "party": BUYER, "quote": "is reserved to the Buyer"},
    {"clause_number": "3", "party": BUYER},
])
def test_an_llm_answer_without_a_verbatim_quote_or_known_party_is_rejected(item):
    result = run(UNPLACED, llm=FakeLLM({"provisions": [item]}))
    assert not any(p.source == "llm" for p in result.provisions)


def test_a_failing_llm_does_not_stop_the_layer(caplog):
    def boom():
        raise RuntimeError("Gemini is down")
    result = run(UNPLACED, llm=FakeLLM(boom))
    assert result.provisions and "LLM fallback failed (RuntimeError)" in caplog.text


def test_no_contract_text_reaches_the_log(caplog):
    with caplog.at_level("INFO", logger="app.pipeline.asymmetry"):
        run(UNPLACED, llm=FakeLLM({"provisions": []}))
    assert "risk asymmetry:" in caplog.text
    assert "Buyer" not in caplog.text and "Elm Example" not in caplog.text and "reserved" not in caplog.text


# --- findings and the Layer 5 gate ------------------------------------------------------------

def test_our_side_must_be_a_party():
    with pytest.raises(ValueError):
        run_risk_asymmetry(doc(ONE_SIDED_TERMINATION), "Someone Else Ltd", config=config(), llm=None)


def test_indemnity_findings_pass_the_layer_5_gate():
    [f] = run(UNCAPPED_INDEMNITY).findings
    context = DocumentContext("vendor_supplier", frozenset({"1", "2", "3"}))
    assert check_finding(f, StubFixtureCorpus(), context).allowed


def test_termination_findings_are_blocked_until_the_corpus_has_that_baseline():
    # Known gap: the stub corpus's baselines are liability-cap, indemnity-scope and penalty-vs-damages only.
    [f] = run(ONE_SIDED_TERMINATION).findings
    decision = check_finding(f, StubFixtureCorpus(), DocumentContext("vendor_supplier", frozenset({"1", "2", "3"})))
    assert not decision.allowed and decision.reason.value == "not_in_baseline"
