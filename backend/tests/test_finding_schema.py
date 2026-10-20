import json
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.finding import INSERT_COLUMNS, CitationType, Finding, FindingStatus, Layer, Severity

EXAMPLE = Path(__file__).resolve().parents[2] / "example_finding.json"


def load_example() -> dict:
    return json.loads(EXAMPLE.read_text())


def test_example_validates():
    f = Finding.model_validate(load_example())
    assert f.layer is Layer.COMPLETENESS
    assert f.severity is Severity.HIGH
    assert f.status is FindingStatus.PENDING


def test_json_round_trip():
    f = Finding.model_validate(load_example())
    data = json.loads(f.model_dump_json())
    assert data == load_example()
    assert Finding.model_validate_json(f.model_dump_json()) == f


def test_layer_accepts_stored_integer():
    assert Finding.model_validate({**load_example(), "layer": 2}).layer is Layer.STATUTORY


def test_layer_numbers_fixed_by_srd():
    # Stored in findings.layer and mirrored by the frontend's PIPELINE_LAYERS: never renumber.
    assert {l.name: l.value for l in Layer} == {
        "INTAKE": 0, "COMPLETENESS": 1, "STATUTORY": 2, "CONSISTENCY": 3,
        "RISK_ASYMMETRY": 4, "CITATION_GATE": 5, "TRIAGE": 6,
    }


def test_insert_row_matches_table():
    f = Finding.model_validate(load_example())
    doc, ver = uuid4(), uuid4()
    row = f.to_insert_row(doc, ver)
    assert tuple(row) == INSERT_COLUMNS
    assert row["layer"] == 1 and row["severity"] == "high" and row["advocate_action"] is None
    assert row["citation"] == f.citation
    assert row["citation_type"] == f.citation_type.value
    assert Finding.from_db_row(row) == f


@pytest.mark.parametrize("status, action", [
    ("pending", None), ("confirmed", "confirm"), ("overridden", "override"), ("added", "add"),
])
def test_status_maps_to_advocate_action(status, action):
    # Must agree with the generated findings.status column in the finding_citation_and_status migration.
    f = Finding.model_validate({**load_example(), "status": status})
    row = f.to_insert_row(uuid4(), uuid4())
    assert row["advocate_action"] == action
    assert Finding.from_db_row(row).status.value == status


@pytest.mark.parametrize("change", [
    {"severity": "info"},
    {"layer": "PROCEDURAL"},
    {"layer": 7},
    {"description": "  "},
    {"rule_applied": "governing law"},
    {"status": "done"},
    {"citation_type": "MADE_UP"},
    {"citation_type": "statutory"},
    {"unknown_field": 1},
])
def test_invalid_findings_rejected(change):
    with pytest.raises(ValidationError):
        Finding.model_validate({**load_example(), **change})


@pytest.mark.parametrize("field", [
    "layer", "severity", "clause_reference", "description",
    "rule_applied", "remedy_suggested", "citation", "citation_type",
])
def test_required_fields(field):
    data = load_example()
    del data[field]
    with pytest.raises(ValidationError):
        Finding.model_validate(data)


def test_citation_type_values_fixed():
    # Stored in findings.citation_type (migration 18 check constraint): never rename or add one here alone.
    assert {c.name: c.value for c in CitationType} == {
        "STATUTORY": "STATUTORY", "CASE": "CASE", "CORPUS": "CORPUS",
        "INTERNAL_BASELINE": "INTERNAL_BASELINE",
    }


@pytest.mark.parametrize("change", [
    {"citation_type": "statute"},                                           # not a value the table accepts
])
def test_citation_type_must_fit_citation(change):
    with pytest.raises(ValidationError):
        Finding.model_validate({**load_example(), **change})


def test_insert_row_carries_citation_type():
    row = Finding.model_validate(load_example()).to_insert_row(uuid4(), uuid4())
    assert row["citation_type"] == "STATUTORY"
