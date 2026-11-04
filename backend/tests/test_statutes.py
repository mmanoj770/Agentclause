"""Tests for statutes normalisation, display mapping, and Corpus lookup (R8 #3)."""
from datetime import date, timedelta
from unittest.mock import MagicMock

import pytest

from app.agents.citation_gate import StubFixtureCorpus
from app.statutes.normalizer import (
    display_status,
    normalise_act_name,
    normalise_section_number,
    normalise_statute_citation,
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

