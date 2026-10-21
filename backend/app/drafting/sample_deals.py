"""
Three sample deals used to check D5 (lead's "done when": three sample deals produce
correct clauses and the diff shows only fact substitutions).

Each deal lists the placeholder clauses to adapt and, per clause, the exact text the
adapted clause must contain. `model_edits` is what a correct model answer looks like;
offline tests feed it in as a fake model, while acceptance_check.py asks real Gemini.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from app.drafting.schemas import DealFacts


@dataclass
class SampleDeal:
    name: str
    deal: DealFacts
    expected: dict[str, list[str]]  # clause_type -> substrings the adapted clause must contain
    model_edits: dict[str, list[dict]] = field(default_factory=dict)


SAMPLE_DEALS: list[SampleDeal] = [
    SampleDeal(
        name="NDA, Bengaluru, 2-year term",
        deal=DealFacts(
            contract_type="nda",
            party_a={"name": "Quenta Technologies Private Limited", "short_name": "Quenta"},
            party_b={"name": "Infosys Limited", "short_name": "Infosys"},
            effective_date=date(2026, 11, 1),
            jurisdiction_city="Bengaluru",
            terms={"nda_term": "2 years", "survival_period": "3 years"},
        ),
        expected={
            "governing_law": ["exclusive jurisdiction of the courts at Bengaluru, India."],
            "nda_term": ["for a period of 2 years from the Effective Date",
                         "for a further period of 3 years after its expiry"],
        },
        model_edits={
            "governing_law": [{"find": "[City]", "replace": "Bengaluru", "fact": "jurisdiction_city"}],
            "nda_term": [{"find": "[Term]", "replace": "2 years", "fact": "nda_term"},
                         {"find": "[Survival Period]", "replace": "3 years", "fact": "survival_period"}],
        },
    ),
    SampleDeal(
        name="Vendor agreement, Mumbai, INR 25 lakh cap",
        deal=DealFacts(
            contract_type="vendor_supplier",
            party_a={"name": "Quenta Technologies Private Limited", "short_name": "Quenta"},
            party_b={"name": "Shree Packaging Works", "short_name": "Supplier"},
            jurisdiction_city="Mumbai",
            terms={"liability_cap": "INR 25,00,000", "payment_period": "30 days"},
        ),
        expected={
            "limitation_of_liability": ["shall not exceed INR 25,00,000, except in the case of fraud"],
            "payment_terms": ["Payment shall be made within 30 days of receipt of a valid invoice."],
            "dispute_resolution": ["The seat of arbitration shall be Mumbai."],
        },
        model_edits={
            "limitation_of_liability": [{"find": "[Amount]", "replace": "INR 25,00,000",
                                         "fact": "liability_cap"}],
            "payment_terms": [{"find": "45 days", "replace": "30 days", "fact": "payment_period"}],
            "dispute_resolution": [{"find": "[City]", "replace": "Mumbai", "fact": "jurisdiction_city"}],
        },
    ),
    SampleDeal(
        name="MSA, Chennai, 60-day termination notice",
        deal=DealFacts(
            contract_type="msa",
            party_a={"name": "Quenta Technologies Private Limited", "short_name": "Quenta"},
            party_b={"name": "Kaveri Cloud Services LLP", "short_name": "Kaveri"},
            jurisdiction_city="Chennai",
            terms={"termination_notice_period": "60 days", "notice_deemed_received": "7 days"},
        ),
        expected={
            "termination_for_convenience": ["upon 60 days prior written notice to the other party"],
            "notices": ["Notices to Quenta Technologies Private Limited shall be sent to its registered office",
                        "notices to Kaveri Cloud Services LLP to its registered office",
                        "shall be deemed received 7 days after dispatch."],
            "dispute_resolution": ["The seat of arbitration shall be Chennai."],
        },
        model_edits={
            "termination_for_convenience": [{"find": "30 days", "replace": "60 days",
                                             "fact": "termination_notice_period"}],
            "notices": [{"find": "[Party A]", "replace": "Quenta Technologies Private Limited", "fact": "party_a_name"},
                        {"find": "[Party B]", "replace": "Kaveri Cloud Services LLP", "fact": "party_b_name"},
                        {"find": "[Notice Days]", "replace": "7 days", "fact": "notice_deemed_received"}],
            "dispute_resolution": [{"find": "[City]", "replace": "Chennai", "fact": "jurisdiction_city"}],
        },
    ),
]


def check_adapted(sample: SampleDeal, clause_type: str, adapted) -> list[str]:
    """Problems with one adapted clause; an empty list means it is correct."""
    problems = []
    for text in sample.expected.get(clause_type, []):
        if text not in adapted.content:
            problems.append(f"missing expected text: {text!r}")
    if adapted.unresolved_placeholders:
        problems.append(f"leftover placeholders: {adapted.unresolved_placeholders}")
    if not adapted.diff_only_facts:
        problems.append("diff contains a change that is not a fact substitution")
    if adapted.status != "adapted":
        problems.append(f"status is {adapted.status}: {adapted.warnings}")
    return problems
