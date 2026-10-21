"""D6 assembly, D7 citations, D8 verified-only output guard."""

import hashlib
from contextlib import contextmanager

from drafting_fixtures import deal, llm_returning, retrieved

from app.drafting.adaptation import adapt_clause
from app.drafting.assembly import assemble_document, default_heading
from app.drafting.citations import format_citation, resolve_citations
from app.drafting.guard import DRAFT_BANNER, DRAFT_LABEL, Audience, render_for


class FakeConn:
    """Stands in for the database: returns the current state of the given adapted clauses."""

    def __init__(self, clauses, **overrides):
        self.rows = {}
        for c in clauses:
            self.rows[str(c.clause_id)] = {"clause_id": c.clause_id, "status": c.verification_status,
                                           "version": c.version, "content": c.original_content}
        for cid, change in overrides.items():
            self.rows[cid].update(change)

    @contextmanager
    def transaction(self):
        yield

    def execute(self, sql, params):
        wanted = set(params[0])
        rows = [r for k, r in self.rows.items() if k in wanted]

        class Result:
            def fetchall(self_inner):
                return rows
        return Result()


def adapted(clause_type, status="staging", **kw):
    return adapt_clause(retrieved(clause_type, status=status, **kw), deal(), llm=llm_returning())


# ---------------- D7 ----------------

def test_known_citations():
    assert format_citation("ICA_s74") == "Section 74, Indian Contract Act, 1872"
    assert format_citation("MSMED_s15") == (
        "Section 15, Micro, Small and Medium Enterprises Development Act, 2006")


def test_unknown_citation_never_guessed():
    r = resolve_citations(["ICA_s74", "XYZ_s9", "ICA_s74", ""])
    assert [c.code for c in r.citations] == ["ICA_s74"]
    assert r.unresolved == ["XYZ_s9"]
    assert format_citation("XYZ_s9") is None


# ---------------- D6 ----------------

def test_numbering_definitions_and_citations():
    doc = assemble_document(
        "Non-Disclosure Agreement", deal(),
        [adapted("confidentiality"), adapted("indemnity"), adapted("governing_law")],
        definitions={"Confidential Information": "means all non-public information disclosed under this Agreement."},
    )
    assert doc.definitions_number == 1
    assert [c.number for c in doc.clauses] == [2, 3, 4]
    assert [d.term for d in doc.definitions] == ["Confidential Information", "Effective Date"]
    assert doc.clauses[1].citations[0].text == "Section 74, Indian Contract Act, 1872"
    assert '("Quenta")' in doc.preamble and "1 November 2026" in doc.preamble


def test_no_definitions_starts_at_one():
    doc = assemble_document("NDA", deal(effective_date=None), [adapted("confidentiality")])
    assert doc.definitions == [] and doc.clauses[0].number == 1
    assert "[Effective Date]" in doc.preamble
    assert any("effective date" in w for w in doc.warnings)


def test_cross_references():
    nda = adapted("confidentiality", content="Subject to {{clause:governing_law}} and {{clause:missing_one}}, "
                                       "each party shall keep information confidential.")
    doc = assemble_document("NDA", deal(), [nda, adapted("governing_law")])
    text = doc.clauses[0].paragraphs[0]
    assert "Subject to Clause 3 and [UNRESOLVED REFERENCE: missing_one]" in text
    assert any("missing_one" in w for w in doc.warnings)


def test_duplicates_and_unused_definitions_reported():
    doc = assemble_document("NDA", deal(), [adapted("confidentiality"), adapted("confidentiality")],
                            definitions={"Purpose": "means evaluating a partnership."})
    assert len(doc.clauses) == 1
    assert any("Duplicate clause type" in w for w in doc.warnings)
    assert any('"Purpose" is not used' in w for w in doc.warnings)


def test_multi_paragraph_numbering_and_headings():
    c = adapted("confidentiality", content="First paragraph.\n\nSecond paragraph.")
    doc = assemble_document("NDA", deal(effective_date=None), [c], headings={"confidentiality": "Confidentiality"})
    out = render_for(doc, "internal").text
    assert "1. CONFIDENTIALITY" in out and "1.1 First paragraph." in out and "1.2 Second paragraph." in out
    assert default_heading("termination_for_convenience") == "Termination for Convenience"


# ---------------- D8 ----------------

def test_lawyer_output_blocked_when_any_clause_is_staging():
    doc = assemble_document("NDA", deal(), [adapted("confidentiality", status="verified"),
                                            adapted("governing_law", status="staging")])
    r = render_for(doc, Audience.lawyer)
    assert r.allowed is False and r.text is None
    assert [b.clause_type for b in r.blocked] == ["governing_law"]


def test_lawyer_output_allowed_when_all_verified():
    c = adapted("confidentiality", status="verified")
    doc = assemble_document("NDA", deal(), [c])
    r = render_for(doc, "lawyer", conn=FakeConn([c]))
    assert r.allowed is True
    assert DRAFT_LABEL not in r.text and DRAFT_BANNER not in r.text
    assert "keep confidential" in r.text


def test_internal_output_labels_staging():
    doc = assemble_document("NDA", deal(), [adapted("confidentiality", status="verified"),
                                            adapted("governing_law", status="staging")])
    r = render_for(doc, Audience.internal)
    assert r.allowed is True and r.text.count(DRAFT_LABEL) == 1
    assert r.text.startswith("NDA\n\n" + DRAFT_BANNER)
    assert f"GOVERNING LAW {DRAFT_LABEL}" in r.text
    assert any("[City]" in i for i in r.issues)


def test_empty_draft_never_goes_to_lawyer():
    doc = assemble_document("NDA", deal(), [])
    assert render_for(doc, "lawyer").allowed is False


class _BrokenConn:
    def transaction(self):
        raise RuntimeError("db down")


def test_db_failure_fails_closed():
    doc = assemble_document("NDA", deal(), [adapted("confidentiality", status="verified")])
    r = render_for(doc, "lawyer", conn=_BrokenConn())
    assert r.allowed is False and r.text is None
    internal = render_for(doc, "internal", conn=_BrokenConn())
    assert internal.allowed and DRAFT_LABEL in internal.text


# ---------------- D8: live re-check of status, version and text ----------------

def _verified_doc():
    c = adapted("confidentiality", status="verified")
    return c, assemble_document("NDA", deal(), [c])


def test_lawyer_output_refused_without_a_live_check():
    _, doc = _verified_doc()
    r = render_for(doc, "lawyer")
    assert r.allowed is False and r.text is None and r.complete is False
    assert any("live database check" in i for i in r.issues)


def test_verified_clause_whose_text_changed_is_blocked():
    c, doc = _verified_doc()
    conn = FakeConn([c], **{str(c.clause_id): {"content": c.original_content + " Amended later."}})
    r = render_for(doc, "lawyer", conn=conn)
    assert r.allowed is False and "text changed" in r.blocked[0].reason


def test_verified_clause_with_a_new_version_is_blocked():
    c, doc = _verified_doc()
    conn = FakeConn([c], **{str(c.clause_id): {"version": 2}})
    r = render_for(doc, "lawyer", conn=conn)
    assert r.allowed is False and "version 1 to 2" in r.blocked[0].reason


def test_clause_demoted_or_deleted_is_blocked():
    c, doc = _verified_doc()
    assert "not verified" in render_for(doc, "lawyer", conn=FakeConn(
        [c], **{str(c.clause_id): {"status": "staging"}})).blocked[0].reason
    empty = FakeConn([c])
    empty.rows.clear()
    assert "no longer exists" in render_for(doc, "lawyer", conn=empty).blocked[0].reason


def test_adapted_text_differs_from_source_but_is_still_allowed():
    """The fingerprint is of the SOURCE clause, so fact substitutions do not trigger a block."""
    c = adapt_clause(retrieved("governing_law", status="verified"), deal(), llm=llm_returning(
        {"find": "[City]", "replace": "Bengaluru", "fact": "jurisdiction_city"}))
    doc = assemble_document("NDA", deal(), [c])
    r = render_for(doc, "lawyer", conn=FakeConn([c]))
    assert r.allowed and "courts at Bengaluru" in r.text and r.complete


def test_complete_flag_reports_leftover_placeholders():
    c = adapt_clause(retrieved("governing_law", status="verified"), deal(jurisdiction_city=None),
                     llm=llm_returning())
    doc = assemble_document("NDA", deal(jurisdiction_city=None), [c])
    r = render_for(doc, "lawyer", conn=FakeConn([c]))
    assert r.allowed is True and r.complete is False
    assert any("[City]" in i for i in r.issues)
    assert hashlib.sha256(c.original_content.encode()).hexdigest() == doc.clauses[0].source_sha256


# ---------------- D6: terms used but never defined ----------------

def test_undefined_term_is_flagged_and_defined_term_is_not():
    clause = adapted("confidentiality")  # uses "Confidential Information"
    flagged = assemble_document("NDA", deal(), [clause])
    assert any('"Confidential Information" looks like a defined term' in w for w in flagged.warnings)
    defined = assemble_document("NDA", deal(), [clause], definitions={
        "Confidential Information": "means all non-public information disclosed under this Agreement."})
    assert not any("looks like a defined term" in w for w in defined.warnings)


def test_names_places_and_statutes_are_not_flagged_as_terms():
    clauses = [adapted("payment_terms"), adapted("governing_law"),
               adapt_clause(retrieved("dispute_resolution"), deal(), llm=llm_returning(
                   {"find": "[City]", "replace": "Bengaluru", "fact": "jurisdiction_city"}))]
    doc = assemble_document("Vendor Agreement", deal(), clauses)
    assert not any("looks like a defined term" in w for w in doc.warnings), doc.warnings


def test_effective_date_used_but_not_given_is_flagged():
    doc = assemble_document("NDA", deal(effective_date=None), [adapted("nda_term")])
    assert any('"Effective Date" looks like a defined term' in w for w in doc.warnings)
    ok = assemble_document("NDA", deal(), [adapted("nda_term")])
    assert not any('"Effective Date" looks like' in w for w in ok.warnings)
