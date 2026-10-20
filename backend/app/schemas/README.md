# Finding Schema (R1)

`finding.py` defines `Finding`, the shape of every finding the review agent returns. The rule engine (R4) and the NDA completeness checker (R3) should build `Finding` objects and nothing else.

## Fields

| Field | Type | Stored in `findings` as |
|---|---|---|
| `finding_id` | UUID, generated if omitted | `id` |
| `layer` | `Layer` (see below) | `layer` (smallint 0–6) |
| `severity` | `Severity`: `critical`, `high`, `medium`, `low` | `severity` |
| `clause_reference` | non-empty string | `clause_reference` |
| `description` | non-empty string | `description` |
| `rule_applied` | rule ID in `UPPER_SNAKE_CASE` | `rule_applied` |
| `remedy_suggested` | non-empty string | `remedy_suggested` |
| `citation` | non-empty string | `citation` (the finding_citation_and_status migration) |
| `citation_type` | `CitationType`: `STATUTORY`, `CASE`, `CORPUS`, `INTERNAL_BASELINE` | `citation_type` (migration 18). A citation starting `Internal:` must be `INTERNAL_BASELINE`, and only such a citation may be. |
| `status` | `FindingStatus`: `pending` (default), `confirmed`, `overridden`, `added` | written as `advocate_action` (`null`, `confirm`, `override`, `add`); read as the generated `status` column (the finding_citation_and_status migration) |

`status` is a generated column, so the database computes it from `advocate_action` and it can't be written directly. The adjudicate and add-finding code keeps writing `advocate_action`, and `status` follows automatically.

Unknown fields are rejected.

### Layers

Fixed by the SRD and mirrored by the frontend's `PIPELINE_LAYERS`. Never renumber them; the numbers are stored in `findings.layer`.

| Value | `Layer` | Pipeline stage |
|---|---|---|
| 0 | `INTAKE` | Intake and normalisation (R2) |
| 1 | `COMPLETENESS` | Completeness (R3) |
| 2 | `STATUTORY` | Statutory compliance (R4, R5 rule engine) |
| 3 | `CONSISTENCY` | Cross-clause consistency (R6) |
| 4 | `RISK_ASYMMETRY` | Risk asymmetry (R7) |
| 5 | `CITATION_GATE` | Citation gate (R8): blocks unresolved citations |
| 6 | `TRIAGE` | Risk triage (R9): routes to review depth |

## Usage

```python
from app.schemas.finding import Finding, Layer, Severity

f = Finding(
    layer=Layer.COMPLETENESS,        # or "COMPLETENESS", or 1
    severity=Severity.HIGH,          # or "high"
    clause_reference="Missing",
    description="No governing-law clause.",
    rule_applied="NDA_GOVERNING_LAW_MISSING",
    remedy_suggested="Add a governing-law and jurisdiction clause.",
    citation="Code of Civil Procedure, 1908, s. 20",
)

f.model_dump_json()                       # JSON for the API / frontend; layer is shown by name
Finding.model_validate_json(raw)          # parse agent output

row = f.to_insert_row(document_id, version_id)   # dict of findings columns, ready to insert
Finding.from_db_row(row)                         # back from a table row
```

To check that the model still matches the database:

```python
from app.schemas.finding import check_table_matches
assert check_table_matches(conn) == []
```

## Example and tests

- `example_finding.json` (repo root): a missing governing-law clause in an NDA.
- `backend/tests/test_finding_schema.py`: validates the example, JSON round-trip, row round-trip, and rejection of bad input. Run with `cd backend && .venv/bin/python -m pytest tests/test_finding_schema.py`.

## Known gaps

- **No `INFO` severity.** `findings_severity_check` only allows low/medium/high/critical.
- `app/findings/schemas.py` (`FindingIn`) still takes `layer` as a plain int and is what `create_findings` uses today.
