"""REVIEW_MODE=stub: labelled sample findings, no model key, NDA only; and the startup checks for the mode."""
import logging
import uuid

import pytest
from fastapi.testclient import TestClient

from app.agents import citation_gate, router as agents_router, stub_review
from app.auth.dependencies import CurrentUser, get_current_user
from app.config import Settings
from app.db import get_conn
from app.main import app
from app.pipeline import runner
from tests.pipeline_fakes import FakeDB, GateAudit, connection_to, fake_transition


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    """Real environment variables beat code defaults, so clear the ones these tests rely on."""
    for name in ("APP_ENV", "REVIEW_MODE", "GEMINI_API_KEY", "DATABASE_URL", "SUPABASE_URL", "CORS_ALLOWED_ORIGINS"):
        monkeypatch.delenv(name, raising=False)


def _settings(**kw):
    return Settings(_env_file=None, **kw)


@pytest.fixture
def db(monkeypatch):
    database = FakeDB()
    monkeypatch.setattr(runner, "transition", fake_transition(database))
    database.gate = GateAudit()
    monkeypatch.setattr(citation_gate, "_pool_connection", database.gate.connection)
    return database


def run(db, from_state="drafted"):
    return stub_review.run_stub_review(db.doc["id"], db.version_id, from_state,
                                       connection=lambda: connection_to(db))


# --- the run -----------------------------------------------------------------------------------

def test_stub_review_saves_labelled_sample_findings_and_hands_to_the_lawyer_queue(db):
    result = run(db)
    assert result["outcome"] == "pending_lawyer_review" and result["stub"] is True
    assert db.doc["state"] == "pending_lawyer_review"
    assert db.findings, "the sample findings that pass the gate are saved"
    # Every finding says it is a sample, wherever it is shown (lawyer list, client view).
    assert all(f["description"].startswith("[STUB] ") for f in db.findings)


def test_stub_review_marks_the_audit_row_and_sends_the_planted_fake_through_the_gate(db):
    run(db)
    created = next(a for a in db.audit if a["action"] == "findings_created")["details"]
    assert created["layers"]["stub_review"]["stub"] is True
    assert [r["action"] for r in db.gate.rows] == ["citation_blocked"]      # the planted fake is blocked, logged


def test_stub_review_reads_no_file_and_calls_no_model(db, monkeypatch):
    def boom(*a, **kw):
        raise AssertionError("stub mode must not read S3 or call a model")
    monkeypatch.setattr("app.storage.s3.read_object", boom)
    monkeypatch.setattr("app.intake.service.normalize", boom)
    assert run(db)["outcome"] == "pending_lawyer_review"


def test_a_failed_stub_save_returns_the_document_to_its_starting_state(db):
    db.fail_on_insert = True
    result = run(db, from_state="revision_in_progress")
    assert (result["outcome"], result["layer"]) == ("failed", "save")
    assert db.doc["state"] == "revision_in_progress" and db.findings == []


def test_a_document_no_longer_under_ai_review_is_left_alone(db):
    db.doc["state"] = "pending_lawyer_review"
    assert run(db) == {"outcome": "skipped"}


# --- the route -----------------------------------------------------------------------------------

class RouteConn:
    def __init__(self, doc_type):
        self.doc = {"id": uuid.uuid4(), "org_id": "org", "assigned_lawyer_id": None, "state": "drafted",
                    "doc_type": doc_type}


@pytest.fixture
def route(monkeypatch):
    seen = {}
    conn = RouteConn("nda")

    def fake_get_document(c, doc_id, user):
        return conn.doc

    monkeypatch.setattr(agents_router, "get_document", fake_get_document)
    monkeypatch.setattr(runner, "start_review",
                        lambda c, user, doc_id: {"state": "under_ai_review", "version_no": 1,
                                                 "version_id": uuid.uuid4(), "from_state": "drafted"})
    monkeypatch.setattr(stub_review, "run_stub_review", lambda *a, **kw: seen.setdefault("task", "stub"))
    monkeypatch.setattr(runner, "run_pipeline", lambda *a, **kw: seen.setdefault("task", "pipeline"))
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(id="u", email=None, role="startup_user",
                                                                     org_id="org")
    app.dependency_overrides[get_conn] = lambda: conn
    yield type("Route", (), {"conn": conn, "seen": seen, "post": lambda s: TestClient(app).post(
        f"/documents/{conn.doc['id']}/review")})()
    app.dependency_overrides.clear()


def test_stub_mode_is_the_default():
    assert _settings().review_mode == "stub"


def test_route_in_stub_mode_returns_202_and_runs_the_stub(route, monkeypatch):
    monkeypatch.setattr(agents_router.settings, "review_mode", "stub")
    r = route.post()
    assert r.status_code == 202 and r.json()["state"] == "under_ai_review"
    assert route.seen == {"task": "stub"}


def test_route_in_stub_mode_refuses_other_contract_types_before_starting(route, monkeypatch):
    monkeypatch.setattr(agents_router.settings, "review_mode", "stub")
    route.conn.doc["doc_type"] = "vendor_supplier"
    r = route.post()
    assert r.status_code == 422 and "NDA" in r.json()["detail"]
    assert route.seen == {}


def test_route_in_pipeline_mode_runs_the_pipeline_for_any_type(route, monkeypatch):
    monkeypatch.setattr(agents_router.settings, "review_mode", "pipeline")
    route.conn.doc["doc_type"] = "vendor_supplier"
    assert route.post().status_code == 202
    assert route.seen == {"task": "pipeline"}


# --- startup checks --------------------------------------------------------------------------------

PROD = dict(app_env="production", database_url="postgresql://u:p@db.example.com:5432/postgres",
            supabase_url="https://abc.supabase.co", cors_allowed_origins="https://app.example.com")


def test_review_mode_is_logged_next_to_the_app_env_line(caplog):
    with caplog.at_level(logging.INFO):
        _settings(app_env="development", review_mode="stub").check_startup()
    assert "startup mode=development review_mode=stub" in caplog.text


def test_unknown_review_mode_is_refused_when_the_settings_load():
    with pytest.raises(ValueError, match="REVIEW_MODE"):
        _settings(review_mode="live")


@pytest.mark.parametrize("raw", ["Stub", " STUB ", "stub"])
def test_review_mode_is_normalised_once_so_startup_and_route_agree(raw):
    assert _settings(review_mode=raw).review_mode == "stub"


def test_review_mode_from_the_environment_is_normalised_too(monkeypatch):
    monkeypatch.setenv("REVIEW_MODE", "  Pipeline ")
    assert _settings().review_mode == "pipeline"


def test_a_capitalised_mode_still_sends_the_route_to_the_stub(route, monkeypatch):
    """The bug this guards: 'Stub' passed startup as stub, then the route's == 'stub' ran the pipeline."""
    monkeypatch.setattr(agents_router, "settings", _settings(review_mode="Stub"))
    assert route.post().status_code == 202
    assert route.seen == {"task": "stub"}


def test_production_pipeline_mode_without_a_gemini_key_refuses_and_names_the_setting():
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        _settings(**PROD, review_mode="pipeline", gemini_api_key="").check_startup()


def test_production_pipeline_mode_with_a_key_starts():
    _settings(**PROD, review_mode="pipeline", gemini_api_key="fake-key-for-test").check_startup()


def test_production_stub_mode_needs_no_key():
    _settings(**PROD, review_mode="stub", gemini_api_key="").check_startup()
