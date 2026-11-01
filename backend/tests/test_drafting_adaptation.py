"""D5: the model can fill in deal facts but can never change legal substance."""

import pytest
from pydantic import ValidationError

from app.drafting.adaptation import AdaptationStatus, adapt_clause
from app.drafting.schemas import DealFacts
from app.gemini import GeminiError
from drafting_fixtures import deal, llm_returning, retrieved


def test_fills_placeholder():
    r = adapt_clause(retrieved("governing_law"), deal(),
                     llm=llm_returning({"find": "[City]", "replace": "Bengaluru", "fact": "jurisdiction_city"}))
    assert r.status == AdaptationStatus.adapted
    assert "courts at Bengaluru, India" in r.content
    assert r.unresolved_placeholders == []
    assert r.original_content != r.content


def test_changes_period_keeping_operator_words():
    r = adapt_clause(retrieved("payment_terms"), deal(),
                     llm=llm_returning({"find": "within 45 days", "replace": "within 30 days",
                                        "fact": "payment_period"}))
    assert r.status == AdaptationStatus.adapted
    assert r.content.startswith("Payment shall be made within 30 days of receipt")


def test_no_edits_means_unchanged():
    clause = retrieved("confidentiality")
    r = adapt_clause(clause, deal(), llm=llm_returning())
    assert r.status == AdaptationStatus.unchanged
    assert r.content == clause.content


@pytest.mark.parametrize("edit, reason_part", [
    # removes legal wording (the confidentiality obligation)
    ({"find": "keep confidential", "replace": "Bengaluru", "fact": "jurisdiction_city"}, "remove legal wording"),
    # removes a negation
    ({"find": "shall not disclose", "replace": "shall disclose Infosys Limited", "fact": "party_b_name"},
     "legal operator"),
    # invents a statute citation (D7: citations must come from metadata)
    ({"find": "prior written consent", "replace": "prior written consent under Section 27 of the Act 60 days",
      "fact": "notice_period"}, "not in the facts"),
    # value not in the facts
    ({"find": "any third party", "replace": "any third party 90 days", "fact": "notice_period"},
     "exact value"),
    # unknown fact key
    ({"find": "third party", "replace": "Bengaluru", "fact": "made_up"}, "unknown fact"),
    # find text not in the clause
    ({"find": "within 7 days", "replace": "within 60 days", "fact": "notice_period"}, "verbatim"),
    # malformed
    ({"find": 5, "replace": "x", "fact": "notice_period"}, "strings"),
])
def test_unsafe_edits_rejected(edit, reason_part):
    clause = retrieved("confidentiality")
    r = adapt_clause(clause, deal(), llm=llm_returning(edit))
    assert r.content == clause.content
    assert r.status == AdaptationStatus.fallback_original
    assert len(r.edits_rejected) == 1
    assert reason_part in r.edits_rejected[0].reason


def test_ambiguous_find_rejected():
    clause = retrieved("confidentiality", content="Notice of 30 days. A further 30 days applies.")
    r = adapt_clause(clause, deal(),
                     llm=llm_returning({"find": "30 days", "replace": "60 days", "fact": "notice_period"}))
    assert r.content == clause.content
    assert "more than once" in r.edits_rejected[0].reason


def test_dropping_qualifier_rejected():
    clause = retrieved("termination_for_convenience")
    r = adapt_clause(clause, deal(),
                     llm=llm_returning({"find": "30 days prior written", "replace": "60 days",
                                        "fact": "notice_period"}))
    assert r.content == clause.content
    assert "legal operator" in r.edits_rejected[0].reason


def test_cross_reference_token_protected():
    clause = retrieved("confidentiality", content="Subject to {{clause:term_30}}, notice of 30 days applies.")
    r = adapt_clause(clause, deal(),
                     llm=llm_returning({"find": "term_30}}, notice of 30", "replace": "60 days",
                                        "fact": "notice_period"}))
    assert r.content == clause.content
    assert "cross-reference" in r.edits_rejected[0].reason


def test_good_and_bad_edits_mixed():
    clause = retrieved("governing_law")
    r = adapt_clause(clause, deal(), llm=llm_returning(
        {"find": "[City]", "replace": "Bengaluru", "fact": "jurisdiction_city"},
        {"find": "laws of India", "replace": "laws of Singapore", "fact": "governing_law"},
    ))
    assert r.status == AdaptationStatus.adapted
    assert "Bengaluru" in r.content and "laws of India" in r.content
    assert len(r.edits_applied) == 1 and len(r.edits_rejected) == 1


def test_overlapping_edits():
    clause = retrieved("termination_for_convenience")
    r = adapt_clause(clause, deal(), llm=llm_returning(
        {"find": "30 days", "replace": "60 days", "fact": "notice_period"},
        {"find": "upon 30 days", "replace": "upon 60 days", "fact": "notice_period"},
    ))
    assert "upon 60 days prior written notice" in r.content
    assert r.edits_rejected[0].reason == "overlaps another edit"


@pytest.mark.parametrize("bad_llm", [
    lambda p, system: (_ for _ in ()).throw(GeminiError("HTTP 429")),
    lambda p, system: ["not", "a", "dict"],
    lambda p, system: {"edits": "nope"},
    lambda p, system: {},
])
def test_model_failure_keeps_original(bad_llm):
    clause = retrieved("payment_terms")
    r = adapt_clause(clause, deal(), llm=bad_llm)
    assert r.status == AdaptationStatus.fallback_original
    assert r.content == clause.content
    assert r.warnings


def test_unfilled_placeholder_reported():
    r = adapt_clause(retrieved("governing_law"), deal(jurisdiction_city=None), llm=llm_returning())
    assert r.unresolved_placeholders == ["[City]"]


def test_prompt_contains_only_given_facts():
    seen = {}
    def spy(prompt, *, system):
        seen["prompt"], seen["system"] = prompt, system
        return {"edits": []}
    adapt_clause(retrieved("payment_terms"), deal(), llm=spy)
    assert "Infosys Limited" in seen["prompt"] and "payment_period" in seen["prompt"]
    assert "NOT change the legal meaning" in seen["system"]


@pytest.mark.parametrize("bad", [
    dict(terms={"Notice Period": "60 days"}),
    dict(terms={"party_a_name": "X"}),
    dict(terms={"fee": ""}),
    dict(party_b={"name": "Quenta Technologies Private Limited"}),
    dict(party_a={"name": "  "}),
])
def test_deal_facts_validation(bad):
    with pytest.raises(ValidationError):
        deal(**bad)


def test_allowed_facts():
    f = deal().allowed_facts()
    assert f["effective_date"] == "1 November 2026"
    assert f["notice_period"] == "60 days"
    assert isinstance(deal(), DealFacts)


# ---------------- party names (lead: "party names" are facts to substitute) ----------------

PARTY_CLAUSE = ("Notices to [Party A] shall be sent to its registered office, "
                "and notices to [Party B] to its registered office.")


def _party_deal():
    return deal(party_a={"name": "Quenta Technologies Pvt. Ltd.", "short_name": "Quenta"},
                party_b={"name": "Shree Packaging Works & Sons LLP"})


def test_party_names_substituted_and_labelled():
    clause = retrieved("confidentiality", content=PARTY_CLAUSE)
    r = adapt_clause(clause, _party_deal(), llm=llm_returning(
        {"find": "[Party A]", "replace": "Quenta Technologies Pvt. Ltd.", "fact": "party_a_name"},
        {"find": "[Party B]", "replace": "Shree Packaging Works & Sons LLP", "fact": "party_b_name"}))
    assert r.status == AdaptationStatus.adapted and r.diff_only_facts
    assert r.content.startswith("Notices to Quenta Technologies Pvt. Ltd. shall be sent")
    assert "notices to Shree Packaging Works & Sons LLP to its" in r.content
    assert [(c.removed, c.fact) for c in r.diff] == [("[Party A]", "party_a_name"), ("[Party B]", "party_b_name")]


def test_short_name_is_labelled_as_the_short_name():
    clause = retrieved("confidentiality", content=PARTY_CLAUSE)
    r = adapt_clause(clause, _party_deal(), llm=llm_returning(
        {"find": "[Party A]", "replace": "Quenta", "fact": "party_a_short_name"}))
    assert r.diff[0].fact == "party_a_short_name"


@pytest.mark.parametrize("find, replace, fact", [
    ("[Party A]", "Shree Packaging Works & Sons LLP", "party_b_name"),   # parties swapped
    ("[Party B]", "Quenta Technologies Pvt. Ltd.", "party_a_name"),      # parties swapped
    ("[Party A]", "Quenta", "party_b_short_name"),                       # wrong party, unknown fact
])
def test_wrong_party_in_a_party_slot_rejected(find, replace, fact):
    clause = retrieved("confidentiality", content=PARTY_CLAUSE)
    d = deal(party_a={"name": "Quenta Technologies Pvt. Ltd.", "short_name": "Quenta"},
             party_b={"name": "Shree Packaging Works & Sons LLP", "short_name": "Shree"})
    r = adapt_clause(clause, d, llm=llm_returning({"find": find, "replace": replace, "fact": fact}))
    assert r.content == clause.content and r.status == AdaptationStatus.fallback_original
    assert r.edits_rejected


def test_edit_that_changes_nothing_is_unchanged_not_adapted():
    clause = retrieved("termination_for_convenience")
    d = deal(terms={"notice_period": "30 days"})
    r = adapt_clause(clause, d, llm=llm_returning({"find": "30 days", "replace": "30 days", "fact": "notice_period"}))
    assert r.status == AdaptationStatus.unchanged and r.edits_applied == [] and r.content == clause.content


def test_prompt_has_a_worked_example_and_the_party_rule():
    seen = {}
    adapt_clause(retrieved("payment_terms"), deal(),
                 llm=lambda p, *, system: seen.update(system=system) or {"edits": []})
    assert "Never swap the parties" in seen["system"] and "Example" in seen["system"]
