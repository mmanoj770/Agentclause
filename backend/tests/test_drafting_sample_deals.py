"""
D5 lead criteria, offline: three sample deals produce correct clauses, the output keeps
the source clause_id and version, no placeholders are left, and the diff against the
source shows only fact substitutions. (The same deals run against real Gemini in
`python -m app.drafting.acceptance_check`.)
"""

import pytest
from drafting_fixtures import deal, llm_returning, retrieved

from app.drafting import adaptation
from app.drafting.adaptation import AdaptationStatus, Edit, adapt_clause, diff_against_source
from app.drafting.sample_deals import SAMPLE_DEALS, check_adapted


@pytest.mark.parametrize("sample", SAMPLE_DEALS, ids=[s.name for s in SAMPLE_DEALS])
def test_three_sample_deals(sample):
    assert len(SAMPLE_DEALS) == 3
    for clause_type, edits in sample.model_edits.items():
        source = retrieved(clause_type)
        out = adapt_clause(source, sample.deal, llm=llm_returning(*edits))
        assert check_adapted(sample, clause_type, out) == [], clause_type
        assert out.clause_id == source.clause_id and out.version == source.version
        assert out.original_content == source.content
        assert out.diff and all(c.fact for c in out.diff)
        # Every inserted value is exactly one of this deal's facts.
        facts = sample.deal.allowed_facts()
        assert {c.fact for c in out.diff} <= set(facts)


def test_diff_shows_each_substitution():
    out = adapt_clause(retrieved("nda_term"), SAMPLE_DEALS[0].deal,
                       llm=llm_returning(*SAMPLE_DEALS[0].model_edits["nda_term"]))
    assert [(c.removed, c.inserted, c.fact) for c in out.diff] == [
        ("[Term]", "2 years", "nda_term"),
        ("[Survival Period]", "3 years", "survival_period"),
    ]


def test_unchanged_clause_has_empty_diff():
    out = adapt_clause(retrieved("confidentiality"), deal(), llm=llm_returning())
    assert out.status == AdaptationStatus.unchanged and out.diff == [] and out.diff_only_facts


@pytest.mark.parametrize("source, adapted", [
    ("each party shall not disclose", "each party shall disclose"),            # negation removed
    ("keep confidential all information", "keep all information"),            # wording deleted
    ("courts at [City], India", "courts at Bengaluru or Mumbai, India"),       # words not in facts
    ("within 45 days of receipt", "within 30 days of written receipt"),        # extra legal word
    ("courts at [City], India", "courts at Bengaluru, Delhi"),                 # 'India' replaced
])
def test_diff_flags_non_fact_changes(source, adapted):
    facts = deal().allowed_facts()  # includes Bengaluru and "30 days"
    assert any(c.fact is None for c in diff_against_source(source, adapted, facts))


@pytest.mark.parametrize("source, adapted", [
    ("courts at [City], India", "courts at Bengaluru, India"),
    ("within 45 days of receipt", "within 30 days of receipt"),
    ("shall not exceed [Amount], except", "shall not exceed INR 25,00,000, except"),
])
def test_diff_accepts_fact_substitutions(source, adapted):
    facts = {**deal().allowed_facts(), "liability_cap": "INR 25,00,000"}
    changes = diff_against_source(source, adapted, facts)
    assert changes and all(c.fact for c in changes)


def test_diff_check_is_an_independent_safety_net(monkeypatch):
    """Even if the edit checks were bypassed, the diff check keeps the original text."""
    def accept_anything(raw, original, facts, xref_spans):
        return Edit(**raw), original.index(raw["find"])
    monkeypatch.setattr(adaptation, "_check_edit", accept_anything)
    source = retrieved("confidentiality")
    out = adapt_clause(source, deal(), llm=llm_returning(
        {"find": "keep confidential", "replace": "Bengaluru", "fact": "jurisdiction_city"}))
    assert out.content == source.content
    assert out.status == AdaptationStatus.fallback_original
    assert any("Diff check failed" in w for w in out.warnings)
