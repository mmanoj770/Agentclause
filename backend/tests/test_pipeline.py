"""R10 pipeline: run the layers for one version, save in one transaction, never leave the document stuck."""
import json
import shutil
import time

import pytest

from app.agents import citation_gate
from app.pipeline import runner
from app.pipeline.runner import PipelineDeps, run_pipeline
from app.rules import api
from tests.pipeline_fakes import FakeDB, GateAudit, canned_normalise, connection_to, fake_transition, fixture_text


@pytest.fixture
def db(monkeypatch):
    database = FakeDB()
    monkeypatch.setattr(runner, "transition", fake_transition(database))
    database.gate = GateAudit()
    monkeypatch.setattr(citation_gate, "_pool_connection", database.gate.connection)
    return database


@pytest.fixture
def verified_rules(monkeypatch, tmp_path):
    """The shipped rule files with verification_status flipped to verified, so strict mode returns findings."""
    for path in api.RULES_DIR.glob("*.json"):
        data = json.loads(path.read_text())
        (tmp_path / path.name).write_text(json.dumps({**data, "verification_status": "verified"}))
    monkeypatch.setattr(api, "RULES_DIR", tmp_path)
    api._rules.cache_clear()
    yield
    api._rules.cache_clear()


def deps(name="nda_bad", **kw) -> PipelineDeps:
    return PipelineDeps(load_text=lambda conn, d, v: fixture_text(name), normalise=canned_normalise(name),
                        our_side=kw.pop("our_side", lambda conn, d, doc: None), **kw)


def run(db, from_state="drafted", **kw):
    return run_pipeline(db.doc["id"], db.version_id, from_state, deps=kw.pop("deps", deps()),
                        connection=lambda: connection_to(db), **kw)


# --- happy path -------------------------------------------------------------------------------

def test_happy_path_ends_in_pending_lawyer_review_with_findings_saved(db, verified_rules):
    result = run(db)
    assert result["outcome"] == "pending_lawyer_review" and db.doc["state"] == "pending_lawyer_review"
    saved = sorted(f["rule_applied"] for f in db.agent_findings())
    assert saved == ["ICA_S27_RESTRAINT_OF_TRADE@1", "ICA_S74_PENALTY_OR_LIQUIDATED_DAMAGES@1",
                     "NDA_GOVERNING_LAW_MISSING@1"]
    assert all(f["document_version_id"] == db.version_id and f["citation"] and f["citation_type"]
               for f in db.findings)
    # Triage stored on the document (critical s.27 finding: at least enhanced) and audited.
    assert db.doc["triage_tier"] == "enhanced"
    assert db.actions() == ["triage_assigned", "findings_created", "state_change"]
    created = next(a for a in db.audit if a["action"] == "findings_created")["details"]
    assert created["count"] == 3 and created["strict"] is True
    assert set(created["layers"]) >= {"R2_intake", "R3_R4_R5_rules", "R6_consistency", "R8_citation_gate", "R9_triage"}


def test_strict_mode_with_only_unverified_rules_still_completes_with_no_findings(db):
    result = run(db)
    assert result["outcome"] == "pending_lawyer_review" and db.findings == []
    assert db.doc["triage_tier"] == "standard"
    stats = result["layers"]["R3_R4_R5_rules"]
    assert stats["findings"] == 0 and stats["skipped"] > 0       # nothing found because nothing verified ran


def test_placeholder_r6_and_r7_add_no_findings_but_the_r7_score_reaches_triage(db, verified_rules):
    side = "Aster Example Technologies Private Limited"
    result = run(db, deps=deps(our_side=lambda conn, d, doc: side))
    assert result["layers"]["R7_asymmetry"]["findings"] == 0
    assert "score" in result["layers"]["R7_asymmetry"]
    assert not any(f["rule_applied"].startswith(("R6_", "R7_")) for f in db.findings)


def test_r7_is_skipped_when_our_side_is_not_known(db):
    assert run(db)["layers"]["R7_asymmetry"] == {"ms": 0.0, "skipped": "no_side"}


def test_only_what_the_gate_passes_is_saved_and_each_block_is_logged(db, verified_rules):
    no_s27 = {k: v for k, v in citation_gate.STUB_STATUTES.items() if k[2] != "27"}
    run(db, deps=deps(corpus=citation_gate.StubFixtureCorpus(statutes=no_s27)))
    assert "ICA_S27_RESTRAINT_OF_TRADE@1" not in {f["rule_applied"] for f in db.findings}
    [row] = db.gate.rows
    assert row["action"] == "citation_blocked" and row["details"]["reason"] == "not_in_corpus"


# --- failure never leaves the document in under_ai_review --------------------------------------

def failing(exc):
    def fn(*a, **kw):
        raise exc
    return fn


@pytest.mark.parametrize("dep, exc, layer", [
    ("load_text", ValueError("unsupported file type: .png"), "R2_intake_load"),
    ("normalise", RuntimeError("model down"), "R2_intake"),
    ("our_side", KeyError("org"), "R7_side"),
])
def test_a_failing_layer_returns_the_document_to_its_starting_state(db, dep, exc, layer):
    d = deps()
    setattr(d, dep, failing(exc))
    result = run(db, deps=d)
    assert result == {"outcome": "failed", "layer": layer, "error_type": type(exc).__name__}
    assert db.doc["state"] == "drafted" and db.findings == [] and db.moves == ["drafted"]
    failed = next(a for a in db.audit if a["action"] == "ai_review_failed")["details"]
    assert failed == {"layer": layer, "error_type": type(exc).__name__, "returned_to": "drafted"}


def test_an_unreadable_corpus_fails_the_review_and_logs_the_abort(db):
    result = run(db, deps=deps(corpus=citation_gate.StubFixtureCorpus(statutes={})))
    assert (result["outcome"], result["layer"]) == ("failed", "R8_citation_gate")
    assert db.doc["state"] == "drafted" and db.findings == []
    assert [r["action"] for r in db.gate.rows] == ["citation_gate_aborted"]


def test_a_failed_save_rolls_back_and_returns_a_revision_to_revision_in_progress(db, verified_rules):
    old = {"document_version_id": db.version_id, "advocate_action": None, "rule_applied": "OLD_AGENT_FINDING"}
    db.findings.append(dict(old))
    db.fail_on_insert = True
    result = run(db, from_state="revision_in_progress")
    assert (result["outcome"], result["layer"], result["error_type"]) == ("failed", "save", "RuntimeError")
    assert db.findings == [old]                          # the delete was rolled back with the failed insert
    assert db.doc["state"] == "revision_in_progress" and db.doc["triage_tier"] is None
    assert "findings_created" not in db.actions()


def test_a_document_no_longer_under_ai_review_is_left_alone(db):
    db.doc["state"] = "pending_lawyer_review"
    assert run(db) == {"outcome": "skipped"}
    assert db.moves == [] and db.audit == []


# --- re-runs ----------------------------------------------------------------------------------

def test_a_rerun_replaces_the_versions_agent_findings_without_duplicates(db, verified_rules):
    run(db)
    first = sorted(f["rule_applied"] for f in db.findings)
    db.doc["state"] = "under_ai_review"
    run(db)
    assert sorted(f["rule_applied"] for f in db.findings) == first and len(db.findings) == 3


def test_lawyer_added_findings_survive_a_rerun(db, verified_rules):
    lawyer = {"document_version_id": db.version_id, "advocate_action": "add", "rule_applied": None,
              "description": "Lawyer's own point"}
    db.findings.append(lawyer)
    run(db)
    db.doc["state"] = "under_ai_review"
    run(db)
    assert lawyer in db.findings and len(db.agent_findings()) == 3


# --- logging and timing -----------------------------------------------------------------------

def test_logs_carry_ids_layers_counts_and_timings_never_contract_text(db, verified_rules, caplog):
    with caplog.at_level("INFO"):
        run(db)
    text = caplog.text
    assert f"document_id={db.doc['id']}" in text and "R3_R4_R5_rules" in text and "ms=" in text
    for secret in ("Aster", "Bramble", "liquidated damages", "Non-Compete", "INR 50,00,000"):
        assert secret not in text


def test_a_mocked_run_takes_well_under_a_second(db, verified_rules):
    started = time.monotonic()
    result = run(db)
    assert result["ms"] < 1000 and time.monotonic() - started < 1


# --- start_review (the route side) ------------------------------------------------------------

class StartConn:
    def __init__(self, state="drafted", stale=False, findings=False):
        self.doc = {"id": "doc-1", "org_id": "org-1", "assigned_lawyer_id": None, "state": state, "doc_type": "nda"}
        self.stale, self.has_findings, self.commits, self.moves = stale, findings, 0, []
        self.audit = []

    def commit(self):
        self.commits += 1

    def transaction(self):
        return connection_to(self)

    def execute(self, sql, params=()):
        from tests.pipeline_fakes import Result
        s = " ".join(sql.split())
        if s.startswith("select (now() - updated_at) > %s as stale"):
            return Result([{"stale": self.stale}] if self.doc["state"] == "under_ai_review" else [])
        if s.startswith("select details->>'from' as from_state from audit_logs"):
            return Result([{"from_state": "revision_in_progress"}])
        if s.startswith("select id, version_no from document_versions"):
            return Result([{"id": "v-1", "version_no": 1}])
        if s.startswith("select 1 from findings where document_version_id"):
            return Result([{"?column?": 1}] if self.has_findings else [])
        if s.startswith("insert into audit_logs"):
            self.audit.append(params[3])
            return Result([])
        raise AssertionError(s)


@pytest.fixture
def start(monkeypatch):
    def make(**kw):
        conn = StartConn(**kw)
        monkeypatch.setattr(runner, "get_document", lambda c, d, u: conn.doc)
        monkeypatch.setattr(runner, "transition", fake_transition(conn))
        return conn
    return make


def test_start_review_moves_to_under_ai_review_and_commits_before_the_background_run(start):
    conn = start()
    assert runner.start_review(conn, None, "doc-1") == {"state": "under_ai_review", "version_no": 1,
                                                       "version_id": "v-1", "from_state": "drafted"}
    assert conn.moves == ["under_ai_review"] and conn.commits == 1


@pytest.mark.parametrize("state", ["pending_lawyer_review", "lawyer_approved", "under_ai_review"])
def test_start_review_rejects_the_wrong_state(start, state):
    conn = start(state=state)
    with pytest.raises(runner.HTTPException) as e:
        runner.start_review(conn, None, "doc-1")
    assert e.value.status_code == 409 and conn.moves == []


def test_a_second_click_is_rejected_while_the_first_run_is_going(start):
    conn = start()
    runner.start_review(conn, None, "doc-1")
    with pytest.raises(runner.HTTPException) as e:
        runner.start_review(conn, None, "doc-1")           # now under_ai_review, and not stale
    assert e.value.status_code == 409 and conn.moves == ["under_ai_review"]


def test_a_stale_run_is_recovered_and_the_review_starts_again(start):
    conn = start(state="under_ai_review", stale=True)
    out = runner.start_review(conn, None, "doc-1")
    assert conn.moves == ["revision_in_progress", "under_ai_review"] and out["from_state"] == "revision_in_progress"
    assert "ai_review_failed" in conn.audit


def test_an_already_reviewed_version_is_409(start):
    with pytest.raises(runner.HTTPException) as e:
        runner.start_review(start(findings=True), None, "doc-1")
    assert e.value.status_code == 409 and "already been reviewed" in e.value.detail
