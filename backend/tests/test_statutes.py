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
