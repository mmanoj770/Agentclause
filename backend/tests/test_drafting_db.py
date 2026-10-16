"""
Database tests for D2/D3/D4 against a real Postgres with the migrations applied.

Skipped unless TEST_DATABASE_URL is set, e.g. for local Supabase:
    TEST_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:54322/postgres python -m pytest
Each test runs inside a transaction that is rolled back, so no data is left behind.
Embeddings here are hand-made vectors (no network); the real Gemini check is
`python -m app.drafting.acceptance_check`.
"""

import os

import pytest

psycopg = pytest.importorskip("psycopg")
from psycopg.rows import dict_row  # noqa: E402

from drafting_fixtures import seed_clauses  # noqa: E402

from app.clauses import embedder  # noqa: E402
from app.clauses.loader import load_clause  # noqa: E402
from app.clauses.seed_runner import SEED_FILE, seed_file  # noqa: E402
from app.drafting.retrieval import retrieve_clauses  # noqa: E402
from app.gemini import GeminiError  # noqa: E402

DB_URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="TEST_DATABASE_URL not set")

TITLES = sorted(c["title"] for c in seed_clauses().values())
TYPE_INDEX = {c["clause_type"]: TITLES.index(c["title"]) for c in seed_clauses().values()}


def onehot(i, dim=768):
    v = [0.0] * dim
    v[i] = 1.0
    return v


@pytest.fixture
def conn():
    c = psycopg.connect(DB_URL, row_factory=dict_row)
    try:
        c.execute("DELETE FROM clauses")  # rolled back at the end
        yield c
    finally:
        c.rollback()
        c.close()


@pytest.fixture
def fake_embeddings(monkeypatch):
    """Each placeholder clause gets its own direction; records every call."""
    calls = []

    def fake(text, title=None):
        calls.append(title)
        return onehot(TITLES.index(title) if title in TITLES else 700)
    monkeypatch.setattr(embedder, "get_embedding", fake)
    return calls


@pytest.fixture
def seeded(conn, fake_embeddings):
    seed_file(conn, SEED_FILE)
    embedder.embed_all_pending(conn)
    fake_embeddings.clear()
    return conn


# ---------------- D2 / D3 ----------------

def test_loader_returns_stored_id(conn):
    cid = load_clause(conn, {"clause_type": "x", "contract_types": ["nda"], "favoured_party": "neutral",
                             "content": "c", "title": "t"})
    assert conn.execute("SELECT 1 FROM clauses WHERE clause_id = %s", (cid,)).fetchone()


def test_at_least_ten_placeholders_all_staging():
    clauses = seed_clauses()
    assert len(clauses) >= 10
    assert all(c["verification_status"] == "staging" for c in clauses.values())
    assert "confidentiality" in clauses


def test_seeding_twice_creates_no_duplicates(conn):
    first = seed_file(conn, SEED_FILE)
    second = seed_file(conn, SEED_FILE)
    assert first == (len(TITLES), 0) and second == (0, len(TITLES))
    assert conn.execute("SELECT count(*) AS n FROM clauses").fetchone()["n"] == len(TITLES)


def test_embedding_twice_is_idempotent(conn, fake_embeddings):
    seed_file(conn, SEED_FILE)
    first = embedder.embed_all_pending(conn)
    assert first.embedded == len(TITLES) and first.reasons == {"new": len(TITLES)}
    second = embedder.embed_all_pending(conn)
    assert second.embedded == 0 and second.skipped == len(TITLES) and not second.failed
    assert len(fake_embeddings) == len(TITLES)  # no extra API calls on the second run
    row = conn.execute("SELECT count(*) AS n FROM clauses WHERE embedding IS NOT NULL "
                       "AND embedding_model = %s AND embedded_version = version",
                       (embedder.current_model(),)).fetchone()
    assert row["n"] == len(TITLES) >= 10


@pytest.mark.parametrize("change, reason", [
    ("UPDATE clauses SET content = content || ' Amended.' WHERE clause_type = 'notices'", "text changed"),
    ("UPDATE clauses SET title = title || ' v2' WHERE clause_type = 'notices'", "text changed"),
    ("UPDATE clauses SET version = 2 WHERE clause_type = 'notices'", "version changed"),
])
def test_reembeds_only_the_changed_clause(seeded, change, reason):
    seeded.execute(change)
    result = embedder.embed_all_pending(seeded)
    assert result.embedded == 1 and result.reasons == {reason: 1}
    assert result.skipped == len(TITLES) - 1


def test_reembeds_everything_when_model_changes(seeded, monkeypatch):
    monkeypatch.setattr(embedder.settings, "gemini_embedding_model", "some-new-model")
    result = embedder.embed_all_pending(seeded)
    assert result.embedded == len(TITLES) and result.reasons == {"model changed": len(TITLES)}


def test_embedding_survives_failures(conn, monkeypatch):
    seed_file(conn, SEED_FILE)

    def flaky(text, title=None):
        if "Indemnity" in title:
            raise GeminiError("quota")
        return onehot(TITLES.index(title))
    monkeypatch.setattr(embedder, "get_embedding", flaky)
    first = embedder.embed_all_pending(conn)
    assert first.embedded == len(TITLES) - 1 and len(first.failed) == 1
    second = embedder.embed_all_pending(conn)  # only the failed one is retried
    assert second.embedded == 0 and len(second.failed) == 1 and second.skipped == len(TITLES) - 1


# ---------------- D4 ----------------

def test_confidentiality_ranks_first_for_nda(seeded):
    # A query vector that is closest to the confidentiality clause, with some overlap elsewhere.
    q = onehot(TYPE_INDEX["confidentiality"])
    q[TYPE_INDEX["permitted_disclosure"]] = 0.5
    r = retrieve_clauses(seeded, None, "nda", "confidentiality", k=3, embed_query=lambda t: q)
    assert [c.clause_type for c in r.clauses[:2]] == ["confidentiality", "permitted_disclosure"]
    assert r.clauses[0].score == pytest.approx(1 / 1.25 ** 0.5, abs=1e-4)
    assert r.clauses[0].score > r.clauses[1].score > r.clauses[2].score
    assert r.unembedded_matches == 0 and r.warnings == []


def test_returns_lead_fields(seeded):
    r = retrieve_clauses(seeded, "payment_terms", "vendor_supplier", "pay", k=1,
                         embed_query=lambda t: onehot(TYPE_INDEX["payment_terms"]))
    data = r.clauses[0].model_dump()
    assert {"clause_id", "version", "statute_refs", "tier", "score"} <= data.keys()
    assert data["tier"] == "staging" and data["version"] == 1
    assert data["statute_refs"] == ["MSMED_s15"] and data["score"] == pytest.approx(1.0)


def test_filters(seeded):
    r = retrieve_clauses(seeded, None, "vendor_supplier", statute_ref="MSMED_s15", k=10)
    assert [c.clause_type for c in r.clauses] == ["payment_terms"] and r.clauses[0].score is None
    r = retrieve_clauses(seeded, None, "nda", favoured_party="party_a", k=10)
    assert [c.clause_type for c in r.clauses] == ["indemnity"]
    r = retrieve_clauses(seeded, None, "nda", k=50)
    assert len(r.clauses) == sum("nda" in c["contract_types"] for c in seed_clauses().values())
    assert len(retrieve_clauses(seeded, None, "nda", k=2).clauses) == 2
    r = retrieve_clauses(seeded, "governing_law", "nda", "law", k=5,
                         embed_query=lambda t: onehot(TYPE_INDEX["confidentiality"]))
    assert [c.clause_type for c in r.clauses] == ["governing_law"]  # filter applied before ranking


@pytest.mark.parametrize("args, kwargs", [
    (("indemnity", "sha"), {}),                         # clause type not used for that contract
    ((None, "employment"), {}),                         # unknown contract type
    (("no_such_clause", "nda", "anything"), {}),        # unknown clause type, with a query
    ((None, "nda"), {"verified_only": True}),           # nothing is verified yet
    ((None, "nda", "x"), {"min_score": 0.99}),          # nothing scores that high
])
def test_empty_results(seeded, args, kwargs):
    r = retrieve_clauses(seeded, *args, embed_query=lambda t: onehot(0, 768), **kwargs)
    assert r.clauses == [] and r.warnings


def test_verified_only(seeded):
    seeded.execute("UPDATE clauses SET verification_status = 'verified', verified_by = 'Adv. Test' "
                   "WHERE clause_type = 'confidentiality'")
    r = retrieve_clauses(seeded, None, "nda", verified_only=True)
    assert [(c.clause_type, c.tier) for c in r.clauses] == [("confidentiality", "verified")]


def test_stale_or_other_model_embeddings_are_not_ranked(seeded, monkeypatch):
    seeded.execute("UPDATE clauses SET content = content || ' Amended.' WHERE clause_type = 'notices'")
    r = retrieve_clauses(seeded, None, "nda", "q", k=50, embed_query=lambda t: onehot(0))
    assert r.unembedded_matches == 1 and "notices" not in [c.clause_type for c in r.clauses]

    monkeypatch.setattr(embedder.settings, "gemini_embedding_model", "some-new-model")
    r = retrieve_clauses(seeded, None, "nda", "q", k=50, embed_query=lambda t: onehot(0))
    assert r.clauses == [] and r.unembedded_matches == 8


def test_api_failure_falls_back_to_filters(seeded):
    def boom(t):
        raise GeminiError("no network")
    r = retrieve_clauses(seeded, None, "nda", "q", k=50, embed_query=boom)
    assert len(r.clauses) == 8 and all(c.score is None for c in r.clauses)
    assert "unavailable" in r.warnings[0]


@pytest.mark.parametrize("args, kwargs", [
    ((None, ""), {}), ((None, "nda"), {"k": 0}), ((None, "nda"), {"k": 51}), ((None, "nda"), {"k": True}),
    ((None, "nda"), {"favoured_party": "bob"}), ((None, "nda"), {"min_score": 0.5}),
    (("", "nda"), {}),
])
def test_bad_arguments(conn, args, kwargs):
    with pytest.raises(ValueError):
        retrieve_clauses(conn, *args, **kwargs)
