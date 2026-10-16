"""
Database tests for D3/D4/D8 against a real Postgres with the migrations applied.

Skipped unless TEST_DATABASE_URL is set, e.g. for local Supabase:
    TEST_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:54322/postgres python -m pytest
Each test runs inside a transaction that is rolled back, so no data is left behind.
"""

import os
from pathlib import Path

import pytest

psycopg = pytest.importorskip("psycopg")
from psycopg.rows import dict_row  # noqa: E402

from drafting_fixtures import SEED_FILE, deal, llm_returning  # noqa: E402

from app.clauses import embedder  # noqa: E402
from app.clauses.loader import load_clause, seed_from_file  # noqa: E402
from app.drafting.adaptation import adapt_clause  # noqa: E402
from app.drafting.assembly import assemble_document  # noqa: E402
from app.drafting.guard import render_for  # noqa: E402
from app.drafting.retrieval import retrieve_clauses  # noqa: E402
from app.gemini import GeminiError  # noqa: E402

DB_URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="TEST_DATABASE_URL not set")


@pytest.fixture
def conn():
    c = psycopg.connect(DB_URL, row_factory=dict_row)
    try:
        c.execute("DELETE FROM clauses")  # rolled back at the end
        yield c
    finally:
        c.rollback()
        c.close()


def onehot(i, dim=768):
    v = [0.0] * dim
    v[i] = 1.0
    return v


@pytest.fixture
def seeded(conn):
    seed_from_file(conn, Path(SEED_FILE))
    rows = conn.execute("SELECT clause_id, clause_type FROM clauses ORDER BY clause_type").fetchall()
    index = {r["clause_type"]: i for i, r in enumerate(rows)}
    for r in rows:
        conn.execute("UPDATE clauses SET embedding = %s::vector WHERE clause_id = %s",
                      (embedder.to_pgvector(onehot(index[r["clause_type"]])), r["clause_id"]))
    return index


def test_loader_returns_stored_id(conn):
    cid = load_clause(conn, {"clause_type": "x", "contract_types": ["nda"], "favoured_party": "neutral",
                             "content": "c", "title": "t"})
    assert conn.execute("SELECT 1 FROM clauses WHERE clause_id = %s", (cid,)).fetchone()


def test_ranked_retrieval(conn, seeded):
    q = onehot(seeded["governing_law"])
    q[seeded["nda_scope"]] = 0.5
    r = retrieve_clauses(conn, contract_type="nda", query="which courts", embed_query=lambda t: q)
    assert [c.clause_type for c in r.clauses[:2]] == ["governing_law", "nda_scope"]
    assert r.clauses[0].similarity == pytest.approx(1 / 1.25 ** 0.5, abs=1e-4)
    assert r.clauses[-1].similarity == pytest.approx(0.0, abs=1e-6)
    assert r.unembedded_matches == 0


def test_filters(conn, seeded):
    r = retrieve_clauses(conn, contract_type="vendor_supplier", statute_ref="MSMED_s15")
    assert [c.clause_type for c in r.clauses] == ["payment_terms"] and r.clauses[0].similarity is None
    r = retrieve_clauses(conn, contract_type="nda", favoured_party="neutral")
    assert {c.clause_type for c in r.clauses} == {"nda_scope", "governing_law"}
    r = retrieve_clauses(conn, contract_type="nda", clause_type="governing_law", top_k=1)
    assert len(r.clauses) == 1
    assert retrieve_clauses(conn, contract_type="sha", clause_type="indemnity").clauses == []


def test_verified_only(conn, seeded):
    assert retrieve_clauses(conn, contract_type="nda", verified_only=True).clauses == []
    conn.execute("UPDATE clauses SET verification_status = 'verified', verified_by = 'Adv. Test' "
                 "WHERE clause_type = 'nda_scope'")
    r = retrieve_clauses(conn, contract_type="nda", verified_only=True)
    assert [c.clause_type for c in r.clauses] == ["nda_scope"]


def test_unembedded_reported_and_api_failure_falls_back(conn, seeded):
    conn.execute("UPDATE clauses SET content = content || ' (edited)' WHERE clause_type = 'indemnity'")
    r = retrieve_clauses(conn, contract_type="nda", query="q", embed_query=lambda t: onehot(0))
    assert r.unembedded_matches == 1 and "indemnity" not in [c.clause_type for c in r.clauses]

    def boom(t):
        raise GeminiError("no network")
    r = retrieve_clauses(conn, contract_type="nda", query="q", embed_query=boom)
    assert len(r.clauses) == 3 and "unavailable" in r.warnings[0]


@pytest.mark.parametrize("kwargs", [dict(contract_type=""), dict(contract_type="nda", top_k=0),
                                    dict(contract_type="nda", top_k=51),
                                    dict(contract_type="nda", favoured_party="bob"),
                                    dict(contract_type="nda", min_similarity=0.5)])
def test_bad_arguments(conn, kwargs):
    with pytest.raises(ValueError):
        retrieve_clauses(conn, **kwargs)


def test_embed_all_pending_is_idempotent_and_survives_failures(conn, monkeypatch):
    seed_from_file(conn, Path(SEED_FILE))
    calls = []

    def fake(text, title=None):
        calls.append(title)
        if "Indemnity" in title:
            raise GeminiError("quota")
        return onehot(len(calls))
    monkeypatch.setattr(embedder, "get_embedding", fake)
    first = embedder.embed_all_pending(conn)
    assert first.embedded == 4 and len(first.failed) == 1
    second = embedder.embed_all_pending(conn)  # only the failed one is retried
    assert second.embedded == 0 and len(second.failed) == 1 and len(calls) == 6


def test_guard_rechecks_database(conn, seeded):
    conn.execute("UPDATE clauses SET verification_status = 'verified', verified_by = 'Adv. Test'")
    r = retrieve_clauses(conn, contract_type="nda", verified_only=True)
    clauses = [adapt_clause(c, deal(), llm=llm_returning(
        {"find": "[City]", "replace": "Bengaluru", "fact": "jurisdiction_city"})) for c in r.clauses]
    doc = assemble_document("Non-Disclosure Agreement", deal(), clauses)
    ok = render_for(doc, "lawyer", conn=conn)
    assert ok.allowed and "courts at Bengaluru, India" in ok.text

    # A clause demoted after retrieval must block lawyer output.
    conn.execute("UPDATE clauses SET verification_status = 'staging' WHERE clause_type = 'indemnity'")
    blocked = render_for(doc, "lawyer", conn=conn)
    assert not blocked.allowed and [b.clause_type for b in blocked.blocked] == ["indemnity"]
    # And a clause deleted from the corpus too.
    conn.execute("DELETE FROM clauses WHERE clause_type = 'indemnity'")
    assert "no longer exists" in render_for(doc, "lawyer", conn=conn).blocked[0].reason
