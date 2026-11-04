"""Tests for statutes normalisation, display mapping, and Corpus lookup (R8 #3)."""
from datetime import date, timedelta
import os
from unittest.mock import MagicMock

import pytest

from app.agents.citation_gate import StubFixtureCorpus
from app.statutes.normalizer import (
    SectionMatchResult,
    display_status,
    normalise_act_name,
    normalise_section_number,
    normalise_statute_citation,
    section_matches,
)


# --- Act Name Normalisation -------------------------------------------------------------------

@pytest.mark.parametrize("raw, expected", [
    ("Indian Contract Act, 1872", "Indian Contract Act, 1872"),
    ("indian contract act", "Indian Contract Act, 1872"),
    ("ICA", "Indian Contract Act, 1872"),
    ("ica", "Indian Contract Act, 1872"),
    ("Contract Act", "Indian Contract Act, 1872"),
    ("Code of Civil Procedure, 1908", "Code of Civil Procedure, 1908"),
    ("CPC", "Code of Civil Procedure, 1908"),
    ("cpc, 1908", "Code of Civil Procedure, 1908"),
    ("MSMED Act", "Micro, Small and Medium Enterprises Development Act, 2006"),
    ("MSMED", "Micro, Small and Medium Enterprises Development Act, 2006"),
    ("msmed, 2006", "Micro, Small and Medium Enterprises Development Act, 2006"),
    ("Specific Relief Act", "Specific Relief Act, 1963"),
    ("SRA", "Specific Relief Act, 1963"),
    ("Arbitration and Conciliation Act", "Arbitration and Conciliation Act, 1996"),
    ("Companies Act", "Companies Act, 2013"),
    ("Unknown Statute 2024", "Unknown Statute 2024"),
])
def test_normalise_act_name(raw, expected):
    assert normalise_act_name(raw) == expected


def test_normalise_act_with_year():
    assert normalise_act_name("ICA", 1872) == "Indian Contract Act, 1872"
    assert normalise_act_name("CPC", 1908) == "Code of Civil Procedure, 1908"


# --- Section Number Normalisation -------------------------------------------------------------

@pytest.mark.parametrize("raw, expected", [
    ("27", "27"),
    ("s. 27", "27"),
    ("s.27", "27"),
    ("Section 27", "27"),
    ("sec 27", "27"),
    ("27(1)", "27(1)"),
    ("s. 27 (1)", "27(1)"),
    ("27(a)", "27(a)"),
    (" 74 ", "74"),
])
def test_normalise_section_number(raw, expected):
    assert normalise_section_number(raw) == expected


def test_section_subsections_are_distinct():
    """27(1), 27(a) and 27 match exactly or not at all."""
    assert normalise_section_number("27") != normalise_section_number("27(1)")
    assert normalise_section_number("27(1)") != normalise_section_number("27(a)")
    assert normalise_section_number("27(1)") == "27(1)"


def test_normalise_statute_citation():
    act, sec = normalise_statute_citation("ICA", 1872, "s. 27")
    assert act == "Indian Contract Act, 1872"
    assert sec == "27"


# --- Display Status Mapping -------------------------------------------------------------------

def test_display_status():
    assert display_status("staging") == "unverified"
    assert display_status("STAGING") == "unverified"
    assert display_status("verified") == "verified"
    assert display_status("VERIFIED") == "verified"


def test_display_status_never_shows_verified_for_staging():
    assert display_status("staging") != "verified"
    with pytest.raises(ValueError):
        display_status("other")


# --- Corpus Lookup Simulation -----------------------------------------------------------------

class DatabaseStatuteCorpus:
    """Simulates gate lookup against public.statutes."""

    def __init__(self, conn, check_date: date | None = None):
        self.conn = conn
        self.check_date = check_date or date(2026, 11, 4)

    def find_statute(self, act: str, year: int, section: str) -> str | None:
        canonical_act, canonical_sec = normalise_statute_citation(act, year, section)
        row = self.conn.execute(
            """
            select id from public.statutes
            where act = %s and section = %s and status = 'verified'
              and effective_from <= %s and (effective_to is null or effective_to > %s)
            """,
            (canonical_act, canonical_sec, self.check_date, self.check_date)
        ).fetchone()
        return str(row["id"]) if row else None


def test_database_corpus_unverified_row_returns_none():
    conn = MagicMock()
    # Mocking: row exists but status='staging', so query returns None
    conn.execute.return_value.fetchone.return_value = None
    corpus = DatabaseStatuteCorpus(conn)
    assert corpus.find_statute("ICA", 1872, "27") is None


def test_database_corpus_verified_row_returns_id():
    conn = MagicMock()
    conn.execute.return_value.fetchone.return_value = {"id": "statute-uuid-1"}
    corpus = DatabaseStatuteCorpus(conn)
    assert corpus.find_statute("ICA", 1872, "27") == "statute-uuid-1"


def test_stub_corpus_is_stub_and_never_counts_as_verified():
    corpus = StubFixtureCorpus()
    assert corpus.is_stub is True
    assert "stub" in corpus.LABEL.lower()
    # Returns stub reference format, never an active database UUID
    assert corpus.find_statute("indian contract act", 1872, "27") == "stub:ica-1872-s27"


# --- Task 2: Single source of truth & asymmetry tests ------------------------------------------

import json
from pathlib import Path
from app.statutes.normalizer import normalize_statute_quote

RULES_DIR = Path(__file__).resolve().parents[1] / "app" / "rules" / "rules"
CONFIG_DIR = Path(__file__).resolve().parents[1] / "app" / "rules" / "config"

# Explicit allowlist of known asymmetries between rules/ and seed_statutes.json:
# 1. Internal baseline rules: completeness checks for NDAs that do not map to external Acts in public.statutes.
KNOWN_RULE_ONLY_STATUTES = {
    ("Internal", "NDA baseline, definition of Confidential Information"): (
        "Internal baseline for NDA completeness; not an external statute in public.statutes."
    ),
    ("Internal", "NDA baseline, governing law"): (
        "Internal baseline for NDA governing law completeness; not an external statute in public.statutes."
    ),
}

# 2. Database seed statutes not yet converted into automated rule files in rules/:
# CPC s. 20 is a baseline for jurisdiction screening in the citation gate, not an automated rule finding.
KNOWN_SEED_ONLY_STATUTES = {
    ("Code of Civil Procedure, 1908", "20"): (
        "CPC s. 20 jurisdiction baseline for citation gate; not currently evaluated as an automated rule in rules/."
    ),
}


def test_statute_quotes_agree_between_rules_and_seed_statutes():
    """Assert that for every (act, section) present in both stores, act, section and quote agree after normalization."""
    seed_path = CONFIG_DIR / "seed_statutes.json"
    assert seed_path.exists(), "seed_statutes.json missing"
    seed_statutes = json.loads(seed_path.read_text(encoding="utf-8"))
    seeds_by_citation = {}
    for s in seed_statutes:
        act_norm, sec_norm = normalise_statute_citation(s["act"], None, s["section"])
        seeds_by_citation[(act_norm, sec_norm)] = s

    rules = []
    for p in RULES_DIR.glob("*.json"):
        r = json.loads(p.read_text(encoding="utf-8"))
        if r.get("statute") and r.get("statute") != "Internal":
            act_norm, sec_norm = normalise_statute_citation(r["statute"], None, str(r["section"]))
            rules.append((act_norm, sec_norm, r))

    assert len(rules) >= 5, "Expected at least 5 statutory rule files"

    agreed_count = 0
    for act_norm, sec_norm, r in rules:
        key = (act_norm, sec_norm)
        if key in seeds_by_citation:
            seed_row = seeds_by_citation[key]
            # Verify Act and section agree
            assert act_norm == normalise_act_name(seed_row["act"])
            assert sec_norm == normalise_section_number(seed_row["section"])

            # Verify quote text agreement (if quote is staged in the rule file)
            r_basis = r.get("basis")
            s_text = seed_row.get("statute_text")
            if r_basis:
                norm_r = normalize_statute_quote(r_basis)
                norm_s = normalize_statute_quote(s_text)
                assert norm_r == norm_s, f"Quote mismatch for {act_norm} s.{sec_norm}:\nRule: {norm_r}\nSeed: {norm_s}"
                agreed_count += 1
            else:
                # s.27 has basis=null in rule file; quote lives in seed_statutes.json
                assert key == ("Indian Contract Act, 1872", "27")

    assert agreed_count >= 4, "Expected at least 4 shared quotes to agree after normalization"


def test_statute_asymmetry_seed_rules_vs_seed_statutes():
    """Verify that every discrepancy between seed rules and seed_statutes.json is documented and accounted for."""
    seed_statutes = json.loads((CONFIG_DIR / "seed_statutes.json").read_text(encoding="utf-8"))
    seed_keys = {
        normalise_statute_citation(s["act"], None, s["section"]): s for s in seed_statutes
    }

    rule_keys = {}
    for p in RULES_DIR.glob("*.json"):
        r = json.loads(p.read_text(encoding="utf-8"))
        statute = r.get("statute")
        sec = str(r.get("section", ""))
        if statute == "Internal":
            key = ("Internal", sec)
        else:
            key = normalise_statute_citation(statute, None, sec)
        rule_keys[key] = r

    # Rules that have no seed_statutes row
    rule_only = {k: rule_keys[k] for k in rule_keys if k not in seed_keys}
    assert set(rule_only.keys()) == set(KNOWN_RULE_ONLY_STATUTES.keys()), (
        f"Unexpected rules without seed_statutes.json entry: {set(rule_only.keys()) - set(KNOWN_RULE_ONLY_STATUTES.keys())}"
    )

    # Seed statutes that have no rule file
    seed_only = {k: seed_keys[k] for k in seed_keys if k not in rule_keys}
    assert set(seed_only.keys()) == set(KNOWN_SEED_ONLY_STATUTES.keys()), (
        f"Unexpected seed_statutes without rule file: {set(seed_only.keys()) - set(KNOWN_SEED_ONLY_STATUTES.keys())}"
    )


# --- Section Matching Rules (R8 #4-6 / Arjun Citation Gate) -----------------------------------

@pytest.mark.parametrize(
    "citation, stored, expected_match, expected_level",
    [
        # Exact matches
        ("27", "27", True, "exact"),
        ("27(1)", "27(1)", True, "exact"),
        ("s. 27", "27", True, "exact"),
        ("27(a)", "27(a)", True, "exact"),
        ("s. 28 (1)(a)", "28(1)(a)", True, "exact"),
        # Subsection matches (citation is base section, stored is subsection)
        ("27", "27(1)", True, "subsection"),
        ("27", "27(a)", True, "subsection"),
        ("27", "27(1)(a)", True, "subsection"),
        ("s. 28", "28(a)", True, "subsection"),
        # Parent fallback (citation specifies subsection, stored is parent base section)
        ("27(1)", "27", True, "parent"),
        ("27(a)", "27", True, "parent"),
        ("s. 74(1)", "74", True, "parent"),
        ("28(1)(a)", "28", True, "parent"),
        # False positives (strictly rejected)
        ("27", "270", False, None),
        ("270", "27", False, None),
        ("27A", "27", False, None),
        ("27", "27A", False, None),
        ("27(1)", "27(2)", False, None),
        ("27(1)", "27(10)", False, None),
        ("27(a)", "27(b)", False, None),
        ("", "27", False, None),
        ("27", "", False, None),
    ],
)
def test_section_matches_table(citation, stored, expected_match, expected_level):
    res = section_matches(citation, stored)
    assert res.matches == expected_match
    assert res.match_level == expected_level


def test_statutes_table_access_permissions():
    """Verify that public.statutes permissions are strictly locked down.

    RLS is enabled with no policies, and SELECT/INSERT/UPDATE/DELETE are revoked
    from 'anon' and 'authenticated' roles. Only 'service_role' (or superuser/owner)
    has access.

    To run against a live/test database, set:
        export TEST_DATABASE_URL="postgresql://postgres:postgres@localhost:54322/postgres"
        pytest backend/tests/test_statutes.py -k test_statutes_table_access_permissions
    """
    db_url = os.environ.get("TEST_DATABASE_URL")
    if not db_url:
        pytest.skip("TEST_DATABASE_URL not set; skipping live DB permissions check")

    import psycopg
    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                select has_table_privilege('anon', 'public.statutes', 'SELECT') as anon_select,
                       has_table_privilege('anon', 'public.statutes', 'INSERT') as anon_insert,
                       has_table_privilege('authenticated', 'public.statutes', 'SELECT') as auth_select,
                       has_table_privilege('authenticated', 'public.statutes', 'INSERT') as auth_insert
            """)
            row = cur.fetchone()
            assert not row[0], "anon must not have SELECT on public.statutes"
            assert not row[1], "anon must not have INSERT on public.statutes"
            assert not row[2], "authenticated must not have SELECT on public.statutes"
            assert not row[3], "authenticated must not have INSERT on public.statutes"


# --- Task 5: verify_statute & load_statutes guard tests ---------------------------------------

import sys
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.verify_statute import verify_statute
from scripts.load_statutes import load_statutes


def test_verify_statute_requires_advocate_and_ref():
    with pytest.raises(SystemExit):
        verify_statute(act="ICA", section="27", advocate="", verification_ref="https://indiacode.nic.in")
    with pytest.raises(SystemExit):
        verify_statute(act="ICA", section="27", advocate="Adv. Sharma", verification_ref="")


def test_verify_statute_records_operator_and_advocate():
    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchone.return_value = {"id": "statute-123", "status": "staging"}
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = mock_conn

    with patch("scripts.verify_statute.pool.open"), \
         patch("scripts.verify_statute.pool.close"), \
         patch("scripts.verify_statute.pool.connection", return_value=mock_ctx), \
         patch("scripts.verify_statute.write_audit") as mock_audit, \
         patch.dict("os.environ", {"USER": "test-dev-user"}):

        verify_statute(
            act="Indian Contract Act, 1872",
            section="27",
            advocate="Adv. Rajesh Kumar",
            verification_ref="https://indiacode.nic.in/handle/123456789/2187",
        )

        # Check update query was run
        assert mock_conn.execute.call_count >= 2
        update_call = mock_conn.execute.call_args_list[1]
        assert "set status = 'verified'" in update_call[0][0]
        assert update_call[0][1][0] == "Adv. Rajesh Kumar"  # verified_by is advocate

        # Check audit event has both operator and advocate
        assert mock_audit.call_count == 1
        audit_kwargs = mock_audit.call_args[1]
        assert audit_kwargs["action"] == "statute_verified"
        assert audit_kwargs["details"]["operator"] == "test-dev-user"
        assert audit_kwargs["details"]["advocate"] == "Adv. Rajesh Kumar"


def test_load_statutes_drift_handling(tmp_path):
    seed_data = [{
        "act": "Indian Contract Act, 1872",
        "section": "27",
        "heading": "Agreement in restraint of trade void",
        "statute_text": "Updated text from seed file",
        "source_url": "https://indiacode.nic.in/handle/123456789/2187",
        "effective_from": "1872-09-01",
        "effective_to": None,
    }]
    seed_file = tmp_path / "seed.json"
    seed_file.write_text(json.dumps(seed_data), encoding="utf-8")

    mock_conn = MagicMock()
    # regclass check succeeds
    mock_conn.execute.return_value.fetchone.side_effect = [
        {"ok": True},  # regclass check
        {"id": "statute-1", "status": "verified", "statute_text": "Old original verified text"},  # row check
    ]
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = mock_conn

    # 1. Verified row cannot be overwritten even if update_staging is True
    with patch("scripts.load_statutes.pool.open"), \
         patch("scripts.load_statutes.pool.close"), \
         patch("scripts.load_statutes.pool.connection", return_value=mock_ctx):

        load_statutes(seed_file, apply=True, update_staging=True)
        # Verify NO update or insert was executed on the verified row
        for call in mock_conn.execute.call_args_list[2:]:
            query = call[0][0].lower()
            assert "update" not in query
            assert "insert" not in query

    # 2. Staging row with drift is updated only when update_staging=True and apply=True
    mock_conn.reset_mock()
    mock_conn.execute.return_value.fetchone.side_effect = [
        {"ok": True},
        {"id": "statute-2", "status": "staging", "statute_text": "Old staging text"},
    ]
    with patch("scripts.load_statutes.pool.open"), \
         patch("scripts.load_statutes.pool.close"), \
         patch("scripts.load_statutes.pool.connection", return_value=mock_ctx):

        load_statutes(seed_file, apply=True, update_staging=True)
        update_calls = [c for c in mock_conn.execute.call_args_list if "update public.statutes" in c[0][0].lower()]
        assert len(update_calls) == 1
        assert "Updated text from seed file" in update_calls[0][0][1]



