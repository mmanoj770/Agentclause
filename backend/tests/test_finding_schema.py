import json
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.finding import INSERT_COLUMNS, Finding, FindingStatus, Layer, Severity

EXAMPLE = Path(__file__).resolve().parents[2] / "example_finding.json"


def load_example() -> dict:
    return json.loads(EXAMPLE.read_text())


def test_example_validates():
    f = Finding.model_validate(load_example())
    assert f.layer is Layer.LEGAL
    assert f.severity is Severity.HIGH
    assert f.status is FindingStatus.PENDING


def test_json_round_trip():
    f = Finding.model_validate(load_example())
    data = json.loads(f.model_dump_json())
    assert data == load_example()
    assert Finding.model_validate_json(f.model_dump_json()) == f


def test_layer_accepts_stored_integer():
    assert Finding.model_validate({**load_example(), "layer": 3}).layer is Layer.LEGAL


def test_insert_row_matches_table():
    f = Finding.model_validate(load_example())
    doc, ver = uuid4(), uuid4()
    row = f.to_insert_row(doc, ver)
    assert tuple(row) == INSERT_COLUMNS
    assert row["layer"] == 3 and row["severity"] == "high" and row["advocate_action"] is None
    assert row["citation"] == f.citation
    assert Finding.from_db_row(row) == f


@pytest.mark.parametrize("status, action", [
    ("pending", None), ("confirmed", "confirm"), ("overridden", "override"), ("added", "add"),
])
def test_status_maps_to_advocate_action(status, action):
    # Must agree with the generated findings.status column in migration 11.
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
    {"unknown_field": 1},
])
def test_invalid_findings_rejected(change):
    with pytest.raises(ValidationError):
        Finding.model_validate({**load_example(), **change})


@pytest.mark.parametrize("field", [
    "layer", "severity", "clause_reference", "description",
    "rule_applied", "remedy_suggested", "citation",
])
def test_required_fields(field):
    data = load_example()
    del data[field]
    with pytest.raises(ValidationError):
        Finding.model_validate(data)
