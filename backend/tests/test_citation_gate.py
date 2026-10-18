"""Layer 5 citation gate: no database. Audit writes go to a fake connection factory."""
import logging
import uuid
from contextlib import contextmanager

import pytest
from fastapi import HTTPException

from app.agents import citation_gate as gate
from app.agents import fixtures
from app.agents.citation_gate import BlockReason, ClauseRecord, DocumentContext, StubFixtureCorpus
from app.schemas.finding import CitationType, Finding, FindingOrigin, Layer, Severity

DOC = uuid.uuid4()
NDA = DocumentContext("nda", frozenset({"3.1", "7", "8", "9.2", "11.2"}))


def make(citation, ctype=CitationType.STATUTORY, layer=Layer.STATUTORY, **kw) -> Finding:
    return Finding(layer=layer, severity=Severity.HIGH, clause_reference="Clause 1",
                   description="d", rule_applied="TEST_RULE", remedy_suggested="r",
                   citation=citation, citation_type=ctype, **kw)


class AuditConn:
    """Stands in for one pooled connection: records rows, and whether its transaction committed."""
    def __init__(self, fail=False):
        self.fail, self.rows, self.committed, self.opened = fail, [], False, 0

    def factory(self):
        @contextmanager
        def cm():
            if self.fail:
                raise RuntimeError("audit database down")
            self.opened += 1
            yield self
        return cm()

    def transaction(self):
        outer = self

        class Tx:
            def __enter__(s): return s
            def __exit__(s, exc_type, *a):
                outer.committed = exc_type is None
                return False
        return Tx()

    def execute(self, sql, params=()):
        assert "insert into audit_logs" in " ".join(sql.split())
        self.rows.append({"document_id": params[0], "actor_id": params[1], "actor_role": params[2],
                          "action": params[3], "details": params[4].obj})


def screen(findings, audit=None, corpus=None, document=NDA):
    audit = audit or AuditConn()
    return gate.screen_findings(findings, DOC, corpus=corpus, document=document, audit_conn=audit.factory), audit


# ---- what passes -------------------------------------------------------------------------------

@pytest.mark.parametrize("citation", [
    "Indian Contract Act, 1872, s. 27",
    "Indian Contract Act, 1872, s. 74",
    "Indian Contract Act, 1872, s.74",
    "Code of Civil Procedure, 1908, s. 20",
    "indian contract act, 1872, s. 27",
    "Micro, Small and Medium Enterprises Development Act, 2006, s. 15",
    "Micro, Small and Medium Enterprises Development Act, 2006, s. 16",
    "Indian Contract Act, 1872,  s. 27",                       # extra ASCII space is collapsed
    "Indian Contract Act, 1872, s. 27; Indian Contract Act, 1872, s. 74",
])
def test_stub_corpus_sections_pass(citation):
    result, audit = screen([make(citation)])
    assert len(result.passed) == 1 and not result.blocked
    assert audit.rows == []
    assert all(r.startswith("stub:") for r in result.passed[0].source_refs)


def test_internal_cross_clause_reference_passes_on_an_allowed_layer():
    f = make("Internal: Clause 3.1 vs Clause 11.2", CitationType.INTERNAL_BASELINE, Layer.CONSISTENCY)
    result, _ = screen([f])
    assert len(result.passed) == 1


def test_the_stub_corpus_is_labelled_and_names_no_statute_text():
    c = StubFixtureCorpus()
    assert c.is_stub and "not lawyer-verified" in c.LABEL
    assert all(ref.startswith("stub:") for ref in gate.STUB_STATUTES.values())


# ---- what is blocked, and logged ---------------------------------------------------------------

def test_planted_fake_citation_is_blocked_and_logged():
    fake = make("Indian Contract Act, 1872, s. 9999")
    real = make("Indian Contract Act, 1872, s. 27")
    result, audit = screen([fake, real])
    assert [p.finding for p in result.passed] == [real]
    assert [b.finding for b in result.blocked] == [fake]
    assert result.blocked[0].reason is BlockReason.NOT_IN_CORPUS
    (row,) = audit.rows
    assert row["action"] == "citation_blocked" and row["document_id"] == DOC
    assert row["actor_role"] == "system" and row["actor_id"] is None
    d = row["details"]
    assert d["citation"] == "Indian Contract Act, 1872, s. 9999"
    assert d["reason"] == "not_in_corpus" and d["corpus_is_stub"] is True
    assert d["payload"]["finding_id"] == str(fake.finding_id) and d["payload"]["citation"] == d["citation"]
    assert audit.committed, "the audit row must be committed on its own transaction"


def test_invented_act_is_blocked():
    result, audit = screen([make("Fake Statute Act, 2020, s. 1")])
    assert result.blocked and not result.passed and len(audit.rows) == 1


@pytest.mark.parametrize("ctype,layer", [
    (CitationType.INTERNAL_BASELINE, Layer.CONSISTENCY),
    (CitationType.STATUTORY, Layer.STATUTORY),
    (CitationType.CASE, Layer.STATUTORY),
    (CitationType.CORPUS, Layer.STATUTORY),
])
def test_internal_made_up_is_blocked_whatever_the_type(ctype, layer):
    result, audit = screen([make("Internal: made up", ctype, layer)])
    assert not result.passed and len(result.blocked) == 1 and len(audit.rows) == 1


def test_internal_prefix_decides_nothing_for_a_statutory_claim():
    # A real-looking internal reference, but the finding claims a STATUTORY source.
    result, _ = screen([make("Internal: Clause 3.1 vs Clause 11.2", CitationType.STATUTORY)])
    assert result.blocked[0].reason is BlockReason.MALFORMED


def test_statute_shaped_text_does_not_pass_as_internal_baseline():
    f = make("Indian Contract Act, 1872, s. 27", CitationType.INTERNAL_BASELINE, Layer.CONSISTENCY)
    result, _ = screen([f])
    assert result.blocked[0].reason is BlockReason.MALFORMED


def test_internal_baseline_on_a_statutory_layer_is_blocked():
    f = make("Internal: Clause 3.1 vs Clause 11.2", CitationType.INTERNAL_BASELINE, Layer.STATUTORY)
    result, _ = screen([f])
    assert result.blocked[0].reason is BlockReason.LAYER_NOT_ALLOWED


@pytest.mark.parametrize("citation", [
    "Indian Contract Act, 1873, s. 27",              # wrong year
    "Indian Contract Act, 1872, s. 28",              # section not in the stub corpus
    "Indian Contract Act, 1872, s. 270",
    "Indian Contract Act, 1872, s. 27A",
    "Indian Contract Act, 1872, s. 27 and s. 74",    # trailing text
    "Indian Contract Act, 1872, s. 27 (Exception 1)",
    "Indian Contract Act, 1872, ss. 27-28",
    "Micro, Small and Medium Enterprises Development Act, 2006, s. 15-16",  # ranges are not guessed
    "Indian Contract Act, 1872, s. 27​",        # zero-width space
    "Indian Contract Act, 1872, s. 27",         # no-break space
    "Indian Contract Act, 1872, s. ２７",    # fullwidth digits
    "Indian Contract Act, 1872, s. 27;",             # empty trailing part
    "Indian Contract Act, 1872, s. 27; Fake Act, 2020, s. 1",   # every part must resolve
    "Contract Act, 1872, s. 27",
    "s. 27",
    "",
    "   ",
])
def test_strict_parsing_blocks_near_misses(citation):
    f = make("x")
    object.__setattr__(f, "citation", citation)   # bypass min_length so the gate itself is tested
    result, audit = screen([f])
    assert len(result.blocked) == 1 and not result.passed and len(audit.rows) == 1


def test_case_citations_are_blocked_until_a_case_corpus_exists():
    result, _ = screen([make("Some v. Other (2020) 1 SCC 1", CitationType.CASE)])
    assert result.blocked[0].reason is BlockReason.NOT_IN_CORPUS


def test_corpus_citations_resolve_only_for_verified_clauses():
    corpus = StubFixtureCorpus(clauses={
        "nda-term": ClauseRecord("stub:clause:nda-term", verified=True),
        "nda-draft": ClauseRecord("stub:clause:nda-draft", verified=False),
    })
    result, _ = screen([make("clause:nda-term", CitationType.CORPUS),
                        make("clause:nda-draft", CitationType.CORPUS),
                        make("clause:missing", CitationType.CORPUS),
                        make("nda-term", CitationType.CORPUS)], corpus=corpus)
    assert [p.finding.citation for p in result.passed] == ["clause:nda-term"]
    assert [b.reason for b in result.blocked] == [
        BlockReason.UNVERIFIED_CLAUSE, BlockReason.NOT_IN_CORPUS, BlockReason.MALFORMED]


def test_stub_review_fixtures_against_the_stub_corpus():
    result, _ = screen(fixtures.sample_findings(), document=fixtures.sample_document_context())
    passed = {p.finding.rule_applied for p in result.passed}
    blocked = {b.finding.rule_applied: b.reason for b in result.blocked}
    assert passed == {"NDA_GOVERNING_LAW_MISSING", "NDA_NON_COMPETE_VOID", "NDA_PENALTY_CLAUSE",
                      "NDA_DEFINITION_MISMATCH"}
    # The real CPC s.20 is in the stub corpus and passes. The only block is the planted fake (ICA s. 999).
    assert blocked == {"NDA_PLANTED_FAKE_CITATION": BlockReason.NOT_IN_CORPUS}


def test_a_mixed_batch_keeps_order_and_logs_one_row_per_block():
    fs = [make("Indian Contract Act, 1872, s. 27"), make("Fake Act, 2000, s. 1"),
          make("Indian Contract Act, 1872, s. 74"), make("Internal: made up", CitationType.INTERNAL_BASELINE,
                                                          Layer.CONSISTENCY)]
    result, audit = screen(fs)
    assert [p.finding for p in result.passed] == [fs[0], fs[2]]
    assert [b.finding for b in result.blocked] == [fs[1], fs[3]]
    assert [r["action"] for r in audit.rows] == ["citation_blocked"] * 2 and audit.opened == 1


def test_no_findings_is_fine():
    result, audit = screen([])
    assert not result.passed and not result.blocked and audit.rows == []


# ---- the corpus cannot be read: abort, log, generic 503 ----------------------------------------

class BrokenLookupCorpus(StubFixtureCorpus):
    def find_statute(self, *a):
        raise OSError("disk read error: /secret/path")


@pytest.mark.parametrize("corpus", [StubFixtureCorpus(statutes={}), StubFixtureCorpus(statutes=None),
                                    BrokenLookupCorpus()])
def test_unreadable_corpus_aborts_with_a_generic_503_and_a_logged_failure(corpus):
    audit = AuditConn()
    with pytest.raises(HTTPException) as e:
        gate.screen_findings([make("Indian Contract Act, 1872, s. 27")], DOC,
                             corpus=corpus, audit_conn=audit.factory)
    assert e.value.status_code == 503 and e.value.detail == gate.GENERIC_503
    assert "corpus" not in e.value.detail.lower() and "secret" not in e.value.detail
    (row,) = audit.rows
    assert row["action"] == "citation_gate_aborted" and row["details"]["reason"] == "corpus_unreadable"
    assert row["document_id"] == DOC and audit.committed


def test_abort_with_a_failing_audit_write_still_503s_and_falls_back_to_the_app_log(caplog):
    with caplog.at_level(logging.ERROR, logger="citation_gate"):
        with pytest.raises(HTTPException) as e:
            gate.screen_findings([make("Indian Contract Act, 1872, s. 27")], DOC,
                                 corpus=StubFixtureCorpus(statutes={}),
                                 audit_conn=AuditConn(fail=True).factory)
    assert e.value.status_code == 503
    assert "citation_gate_aborted" in caplog.text and str(DOC) in caplog.text


def test_failed_block_log_falls_back_to_the_app_log_and_the_block_still_holds(caplog):
    with caplog.at_level(logging.ERROR, logger="citation_gate"):
        result, _ = screen([make("Fake Act, 2000, s. 1")], audit=AuditConn(fail=True))
    assert len(result.blocked) == 1 and not result.passed
    assert "Fake Act, 2000, s. 1" in caplog.text


def test_the_gate_writes_nothing_to_the_callers_connection():
    # screen_findings takes no caller connection at all: its audit rows cannot join the caller's
    # transaction, so a rollback there cannot erase them.
    import inspect
    assert "conn" not in inspect.signature(gate.screen_findings).parameters


# ---- INTERNAL_BASELINE resolves against the real document (Tejaswi's review) -------------------------

def internal(citation, layer):
    return make(citation, CitationType.INTERNAL_BASELINE, layer)


def reason_of(result):
    assert len(result.blocked) == 1 and not result.passed
    return result.blocked[0].reason


def test_internal_clause_that_exists_passes_on_layer_3():
    result, audit = screen([internal("Internal: Clause 3.1 vs Clause 11.2", Layer.CONSISTENCY)])
    assert len(result.passed) == 1 and audit.rows == []


@pytest.mark.parametrize("citation", [
    "Internal: Clause 99 vs Clause 11.2",     # well formed, first clause does not exist
    "Internal: Clause 3.1 vs Clause 99",      # second clause does not exist
    "Internal: Clause 3 vs Clause 11.2",      # "3" is not "3.1": matching is exact
    "Internal: Clause 12 vs Clause 13",
])
def test_internal_reference_to_a_clause_the_document_lacks_is_blocked_and_logged(citation):
    result, audit = screen([internal(citation, Layer.CONSISTENCY)])
    assert reason_of(result) is BlockReason.CLAUSE_NOT_IN_DOCUMENT
    (row,) = audit.rows
    assert row["action"] == "citation_blocked" and row["details"]["reason"] == "clause_not_in_document"


def test_layer_3_pair_needs_two_different_clauses():
    result, _ = screen([internal("Internal: Clause 3.1 vs Clause 3.1", Layer.CONSISTENCY)])
    assert reason_of(result) is BlockReason.MALFORMED


def test_layer_4_needs_the_clause_and_a_baseline_entry():
    ok, _ = screen([internal("Internal: Clause 7 baseline:liability-cap", Layer.RISK_ASYMMETRY)])
    assert len(ok.passed) == 1 and ok.passed[0].source_refs == ("stub:baseline-liability-cap",)
    no_clause, _ = screen([internal("Internal: Clause 70 baseline:liability-cap", Layer.RISK_ASYMMETRY)])
    assert reason_of(no_clause) is BlockReason.CLAUSE_NOT_IN_DOCUMENT
    no_entry, _ = screen([internal("Internal: Clause 7 baseline:made-up", Layer.RISK_ASYMMETRY)])
    assert reason_of(no_entry) is BlockReason.NOT_IN_BASELINE


def test_the_stub_baseline_entries_are_labelled_stub():
    assert all(ref.startswith("stub:") for ref in gate.STUB_BASELINES.values())


def test_layer_1_resolves_against_the_schema_not_the_document():
    # "indemnity" is a required NDA clause that is absent from the document: that is the finding.
    assert "indemnity" not in " ".join(NDA.clause_numbers)
    ok, audit = screen([internal("Internal: Schema nda/indemnity", Layer.COMPLETENESS)])
    assert len(ok.passed) == 1 and audit.rows == []
    assert ok.passed[0].source_refs == ("stub:schema-nda-indemnity",)


@pytest.mark.parametrize("citation", [
    "Internal: Schema nda/made_up_entry",    # no such entry
    "Internal: Schema msa/indemnity",        # entry for a different document type
])
def test_layer_1_schema_reference_that_does_not_resolve_is_blocked(citation):
    result, audit = screen([internal(citation, Layer.COMPLETENESS)])
    assert reason_of(result) is BlockReason.NOT_IN_SCHEMA and len(audit.rows) == 1


def test_each_layer_accepts_only_its_own_internal_shape():
    pair = "Internal: Clause 3.1 vs Clause 11.2"
    for layer in (Layer.COMPLETENESS, Layer.RISK_ASYMMETRY):
        result, _ = screen([internal(pair, layer)])
        assert reason_of(result) is BlockReason.MALFORMED
    result, _ = screen([internal("Internal: Schema nda/indemnity", Layer.CONSISTENCY)])
    assert reason_of(result) is BlockReason.MALFORMED


@pytest.mark.parametrize("layer", [Layer.INTAKE, Layer.STATUTORY, Layer.CITATION_GATE, Layer.TRIAGE])
@pytest.mark.parametrize("citation", [
    "Internal: Clause 3.1 vs Clause 11.2", "Internal: Schema nda/indemnity",
    "Internal: Clause 7 baseline:liability-cap",
])
def test_internal_citation_on_layers_0_2_5_6_is_blocked_and_logged(layer, citation):
    result, audit = screen([internal(citation, layer)])
    assert reason_of(result) is BlockReason.LAYER_NOT_ALLOWED
    assert [r["action"] for r in audit.rows] == ["citation_blocked"]


def test_internal_citation_without_a_document_clause_list_is_blocked_not_assumed_fine():
    result, audit = screen([internal("Internal: Clause 3.1 vs Clause 11.2", Layer.CONSISTENCY)], document=None)
    assert reason_of(result) is BlockReason.NO_DOCUMENT_CONTEXT and len(audit.rows) == 1


# ---- exact matching, the manifest, and fail-closed -----------------------------------------------

def doc_with(*numbers, doc_type="nda"):
    return DocumentContext(doc_type, frozenset(numbers))


def test_clause_3_1_does_not_match_3_10_in_either_direction():
    only_3_10 = doc_with("3.10", "11.2")
    result, _ = screen([internal("Internal: Clause 3.1 vs Clause 11.2", Layer.CONSISTENCY)], document=only_3_10)
    assert reason_of(result) is BlockReason.CLAUSE_NOT_IN_DOCUMENT
    only_3_1 = doc_with("3.1", "11.2")
    result, _ = screen([internal("Internal: Clause 3.10 vs Clause 11.2", Layer.CONSISTENCY)], document=only_3_1)
    assert reason_of(result) is BlockReason.CLAUSE_NOT_IN_DOCUMENT
    result, _ = screen([internal("Internal: Clause 3.1 baseline:liability-cap", Layer.RISK_ASYMMETRY)],
                       document=only_3_10)
    assert reason_of(result) is BlockReason.CLAUSE_NOT_IN_DOCUMENT


@pytest.mark.parametrize("citation", [
    "Internal: Clause 03.1 vs Clause 11.2",     # leading zero is a different string
    "Internal: Clause 3.1. vs Clause 11.2",     # trailing dot
    "Internal: Clause 3.1 vs Clause 11.2 ",     # trailing text is only trimmed spaces: still resolves
])
def test_near_miss_clause_numbers(citation):
    result, _ = screen([internal(citation, Layer.CONSISTENCY)])
    if citation.endswith(" "):
        assert len(result.passed) == 1
    else:
        assert not result.passed and len(result.blocked) == 1


def test_a_well_formed_reference_to_a_missing_clause_blocks_on_every_internal_layer():
    cases = [("Internal: Clause 40 vs Clause 11.2", Layer.CONSISTENCY),
             ("Internal: Clause 40 baseline:liability-cap", Layer.RISK_ASYMMETRY)]
    for citation, layer in cases:
        result, audit = screen([internal(citation, layer)])
        assert reason_of(result) is BlockReason.CLAUSE_NOT_IN_DOCUMENT and len(audit.rows) == 1


def test_layer_1_uses_the_documents_own_type_not_the_citation_string():
    result, _ = screen([internal("Internal: Schema msme/indemnity", Layer.COMPLETENESS)])
    assert reason_of(result) is BlockReason.NOT_IN_SCHEMA            # an NDA citing another type's schema
    other_doc = doc_with("1", doc_type="msme")
    result, _ = screen([internal("Internal: Schema nda/indemnity", Layer.COMPLETENESS)], document=other_doc)
    assert reason_of(result) is BlockReason.NOT_IN_SCHEMA            # the string cannot choose the type
    result, _ = screen([internal("Internal: Schema nda/indemnity", Layer.COMPLETENESS)],
                       document=DocumentContext("", None))
    assert reason_of(result) is BlockReason.NOT_IN_SCHEMA            # no doc type: blocked


def test_no_manifest_blocks_layers_3_and_4_but_layer_1_needs_only_the_doc_type():
    no_manifest = DocumentContext("nda", None)
    for citation, layer in [("Internal: Clause 3.1 vs Clause 11.2", Layer.CONSISTENCY),
                            ("Internal: Clause 7 baseline:liability-cap", Layer.RISK_ASYMMETRY)]:
        result, audit = screen([internal(citation, layer)], document=no_manifest)
        assert reason_of(result) is BlockReason.NO_CLAUSE_MANIFEST
        assert audit.rows[0]["details"]["reason"] == "no_clause_manifest"
    result, audit = screen([internal("Internal: Schema nda/indemnity", Layer.COMPLETENESS)], document=no_manifest)
    assert len(result.passed) == 1 and audit.rows == []


def test_an_empty_manifest_is_not_a_missing_manifest_and_blocks_every_clause_reference():
    result, _ = screen([internal("Internal: Clause 3.1 vs Clause 11.2", Layer.CONSISTENCY)],
                       document=DocumentContext("nda", frozenset()))
    assert reason_of(result) is BlockReason.CLAUSE_NOT_IN_DOCUMENT


def test_a_stub_manifest_feeds_the_gate_through_from_manifest():
    ctx = DocumentContext.from_manifest("nda", fixtures.sample_clause_manifest())
    assert ctx == fixtures.sample_document_context()
    assert DocumentContext.from_manifest("nda", None).clause_numbers is None


def test_statutory_citations_do_not_need_a_document_context():
    result, _ = screen([make("Indian Contract Act, 1872, s. 27")], document=None)
    assert len(result.passed) == 1


# ---- the one exemption: lawyer-added findings, by origin ----------------------------------------------

def advocate_finding(**kw):
    # A lawyer-added finding has no layer and no agent citation, so the full model cannot build one yet
    # (the lawyer-added read model is a separate task); model_construct stands in for it.
    return Finding.model_construct(origin=FindingOrigin.ADVOCATE, severity=Severity.HIGH,
                                   description="added by the advocate", **kw)


def test_advocate_origin_finding_is_exempt_by_rule_and_logs_nothing():
    f = advocate_finding()
    result, audit = screen([f])
    assert [p.finding for p in result.passed] == [f] and not result.blocked and audit.rows == []
    assert gate.GATE_EXEMPT_ORIGINS == frozenset({FindingOrigin.ADVOCATE})


def test_an_agent_finding_with_no_layer_is_never_exempt():
    f = Finding.model_construct(origin=FindingOrigin.AGENT, severity=Severity.HIGH, description="d",
                                citation="Indian Contract Act, 1872, s. 27", citation_type=CitationType.STATUTORY)
    result, audit = screen([f])
    assert reason_of(result) is BlockReason.MALFORMED and len(audit.rows) == 1


def test_an_agent_finding_with_no_layer_and_no_citation_is_blocked_too():
    result, _ = screen([Finding.model_construct(severity=Severity.HIGH, description="d")])
    assert reason_of(result) is BlockReason.MALFORMED


def test_origin_defaults_to_agent_so_agent_output_is_always_gated():
    assert make("Indian Contract Act, 1872, s. 27").origin is FindingOrigin.AGENT


def test_an_advocate_origin_finding_that_carries_agent_fields_is_blocked_as_inconsistent():
    # Agent output cannot talk its way past the gate by claiming origin=advocate.
    f = make("Fake Act, 2000, s. 1", origin=FindingOrigin.ADVOCATE)
    result, audit = screen([f])
    assert reason_of(result) is BlockReason.MALFORMED and len(audit.rows) == 1
