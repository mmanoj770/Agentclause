"""Clause manifest shape (app/schemas/clause_manifest.py): what the Drafting Agent will emit per version."""
import pytest
from pydantic import ValidationError

from app.schemas.clause_manifest import ClauseManifest, ManifestClause


def clause(n, **kw):
    return ManifestClause(clause_number=n, **kw)


@pytest.mark.parametrize("n", ["1", "3", "3.1", "11.2", "3.10", "10", "1.0"])
def test_valid_clause_numbers(n):
    assert clause(n).clause_number == n


@pytest.mark.parametrize("n", ["", "03", "3.", ".3", "3..1", "3.1.", "a", "3.a", " 3", "3 ", "Clause 3", "３"])
def test_invalid_clause_numbers(n):
    with pytest.raises(ValidationError):
        clause(n)


def test_corpus_id_and_version_travel_together():
    assert clause("2", corpus_clause_id="confidentiality-v1", corpus_version="1").corpus_clause_id
    assert clause("2").corpus_clause_id is None
    with pytest.raises(ValidationError):
        clause("2", corpus_clause_id="confidentiality-v1")
    with pytest.raises(ValidationError):
        clause("2", corpus_version="1")


def test_numbers_are_unique_and_3_1_is_not_3_10():
    m = ClauseManifest(version_no=2, produced_by="drafting_agent", clauses=(clause("3.1"), clause("3.10")))
    assert m.clause_numbers == frozenset({"3.1", "3.10"}) and not m.is_stub
    with pytest.raises(ValidationError):
        ClauseManifest(version_no=1, produced_by="drafting_agent", clauses=(clause("3"), clause("3")))


def test_unknown_fields_and_producers_are_rejected():
    with pytest.raises(ValidationError):
        ClauseManifest(version_no=1, produced_by="somebody", clauses=())
    with pytest.raises(ValidationError):
        ClauseManifest(version_no=1, produced_by="stub_fixture", clauses=(), extra=1)
    with pytest.raises(ValidationError):
        ClauseManifest(version_no=0, produced_by="stub_fixture", clauses=())
