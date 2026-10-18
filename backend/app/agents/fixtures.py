"""Fixed sample output for the X1 stub agents. Nothing here is legal advice or verified.

Findings use the R1 `Finding` model, so the real Review Agent can replace `sample_findings()`
without any change to the table or the API. Rule IDs and citations are placeholders until the
lawyer verifies the rulebook (see the build plan, "On hold until the lawyer verifies the data").
"""
import re

from app.schemas.finding import CitationType, Finding, Layer, Severity

STUB_TAG = "[STUB] "


def sample_findings() -> list[Finding]:
    return [
        Finding(
            layer=Layer.COMPLETENESS, severity=Severity.HIGH, clause_reference="Missing",
            description=STUB_TAG + "No governing-law and jurisdiction clause.",
            rule_applied="NDA_GOVERNING_LAW_MISSING",
            remedy_suggested="Add a governing-law and jurisdiction clause naming Indian law and a seat.",
            citation="Code of Civil Procedure, 1908, s. 20", citation_type=CitationType.STATUTORY,
        ),
        Finding(
            layer=Layer.STATUTORY, severity=Severity.CRITICAL, clause_reference="Clause 8",
            description=STUB_TAG + "Post-termination non-compete restrains trade and is likely void.",
            rule_applied="NDA_NON_COMPETE_VOID",
            remedy_suggested="Delete the non-compete or narrow it to confidentiality and non-solicitation.",
            citation="Indian Contract Act, 1872, s. 27", citation_type=CitationType.STATUTORY,
        ),
        Finding(
            layer=Layer.STATUTORY, severity=Severity.MEDIUM, clause_reference="Clause 9.2",
            description=STUB_TAG + "Fixed penalty for breach is not a genuine pre-estimate of loss.",
            rule_applied="NDA_PENALTY_CLAUSE",
            remedy_suggested="Replace the fixed sum with reasonable compensation for proven loss.",
            citation="Indian Contract Act, 1872, s. 74", citation_type=CitationType.STATUTORY,
        ),
        Finding(
            layer=Layer.CONSISTENCY, severity=Severity.LOW, clause_reference="Clause 3 / Clause 11",
            description=STUB_TAG + "'Confidential Information' is defined differently in two clauses.",
            rule_applied="NDA_DEFINITION_MISMATCH",
            remedy_suggested="Keep one definition in Clause 3 and refer to it from Clause 11.",
            citation="Internal: Clause 3.1 vs Clause 11.2", citation_type=CitationType.INTERNAL_BASELINE,
        ),
    ]


# ---- Conversational agent (C1 contract: question in, answer / citations / status out) ----

ADVICE = re.compile(
    r"\b(should (i|we)|can (i|we) sue|am i liable|are we liable|will (i|we) win|my chances|"
    r"my situation|my case|what (do|should) i do|is it safe for (me|us)|advise (me|us))\b", re.I)

# Each topic: trigger words -> a canned grounded answer with one clause citation.
TOPICS: list[tuple[re.Pattern, str, str, str]] = [
    (re.compile(r"confiden|disclos|secret", re.I),
     "The receiving party must keep the disclosing party's information secret and use it only for the stated purpose.",
     "Clause 2", "Each party shall keep Confidential Information secret and use it solely for the Purpose."),
    (re.compile(r"term\b|duration|how long|expire", re.I),
     "The agreement lasts for the term stated in the contract, and confidentiality continues for a set period after it ends.",
     "Clause 6", "This Agreement continues for the Term, and the duties in Clause 2 survive for the Survival Period."),
    (re.compile(r"governing|jurisdiction|court|law", re.I),
     "The contract names the law that governs it and the courts that can hear a dispute.",
     "Clause 12", "This Agreement is governed by the laws of India, with the courts of the stated seat having jurisdiction."),
    (re.compile(r"terminat|end the", re.I),
     "Either party can end the agreement by written notice, as the termination clause sets out.",
     "Clause 7", "Either party may terminate this Agreement by giving written notice as stated in this Clause."),
]
IN_SCOPE = re.compile(
    r"\b(clause|agreement|contract|document|party|parties|notice|liabilit\w*|indemn\w*|payment|"
    r"term|confiden\w*|governing|jurisdiction|terminat\w*|disclos\w*)\b", re.I)

# Refused and escalated replies carry a reason and no answer or citations (C1).
ESCALATED_REASON = ("That needs legal judgment about your own situation. I can only explain what this "
                    "document says. You can book a consultation with the advocate who settled it.")
REFUSED_REASON = "I can only answer questions about this document and the advocate's notes."


def chat_reply(question: str) -> dict:
    """Stub classifier. Advice first (escalate), then scope (refuse), then a canned answer."""
    if ADVICE.search(question):
        return {"status": "escalated", "answer": None, "citations": [], "reason": ESCALATED_REASON}
    if not IN_SCOPE.search(question):
        return {"status": "refused", "answer": None, "citations": [], "reason": REFUSED_REASON}
    for pattern, answer, clause, quote in TOPICS:
        if pattern.search(question):
            return {"status": "answered", "answer": answer,
                    "citations": [{"clause_reference": clause, "quote": quote}], "reason": None}
    return {"status": "answered",
            "answer": "This is covered in the document, but the stub agent has no canned answer for it yet.",
            "citations": [{"clause_reference": "Clause 1", "quote": "Definitions and interpretation."}],
            "reason": None}


# ---- Drafting agent ----

def sample_draft(disclosing: str, receiving: str, effective_date: str, term_months: int,
                 seat: str, mutual: bool) -> dict:
    kind = "Mutual" if mutual else "One-way"
    clauses = [
        ("1", "Parties", f"This {kind} Non-Disclosure Agreement is made on {effective_date} between "
                         f"{disclosing} (the Disclosing Party) and {receiving} (the Receiving Party).",
         "Indian Contract Act, 1872, s. 10"),
        ("2", "Confidentiality", "The Receiving Party shall keep Confidential Information secret and "
                                 "use it only for the Purpose.", "Indian Contract Act, 1872, s. 10"),
        ("3", "Term", f"This Agreement runs for {term_months} months from the date above.",
         "Indian Contract Act, 1872, s. 10"),
        ("4", "Governing law", f"This Agreement is governed by the laws of India. The courts at "
                               f"{seat} have jurisdiction.", "Code of Civil Procedure, 1908, s. 20"),
    ]
    return {
        "draft_label": "STUB DRAFT: staging clauses, not lawyer-verified",
        "source_tier": "staging",
        "clauses": [{"clause_no": n, "heading": h, "text": t, "citation": c, "source_tier": "staging"}
                    for n, h, t, c in clauses],
    }
