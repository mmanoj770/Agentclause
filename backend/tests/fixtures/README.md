# Fixture contracts (R11)

Synthetic contracts with planted defects, and the findings each one must produce. `tests/test_fixture_contracts.py` runs every fixture through the review chain and fails on a missed defect **and** on a false positive.

**Invented data only.** Use made-up company names (the existing ones all contain "Example"), made-up people and made-up amounts. Never paste a real contract, even an edited one.

## The files for one contract

Each fixture is three files in `contracts/` with the same name:

| File | What it holds |
|---|---|
| `<name>.txt` | The contract text |
| `<name>.intake.json` | What the intake LLM would return for it: the JSON matching `EXTRACTION_SCHEMA` in `app/intake/service.py`, including `is_contract`. The tests feed this to `IntakeService` in place of the real model, so no API is called |
| `<name>.expected_findings.json` | What the review must find (below) |

The test picks up every `*.txt` file automatically. Then update the fixture list in `test_there_are_fixtures_and_each_has_all_three_files`, and the planted-defect totals in `test_every_planted_defect_is_found_in_demo_mode`.

## `expected_findings.json`

```json
{
  "contract_type": "nda",
  "planted_defects": [{"defect": "No governing law clause", "rule_id": "NDA_GOVERNING_LAW_MISSING"}],
  "demo":   [{"rule_applied": "NDA_GOVERNING_LAW_MISSING@1", "layer": "COMPLETENESS", "severity": "low"}],
  "strict": [],
  "layers": {
    "R3_completeness": ["NDA_GOVERNING_LAW_MISSING"],
    "R4_R5_rules": ["NDA_GOVERNING_LAW_MISSING@1"]
  },
  "gate_blocked_known_gaps": [
    {"rule_applied": "NDA_GOVERNING_LAW_MISSING@1", "reason": "malformed", "gap": "R8 #1: internal citation format"}
  ]
}
```

| Key | Meaning |
|---|---|
| `contract_type` | A `contract_types` code. It must match `document_type` in the intake file |
| `planted_defects` | One entry per defect you put in on purpose, with the bare rule ID that should catch it. This is what recall is measured against |
| `demo` | **Every** finding `run_review(..., strict=False)` returns, no more and no fewer. `rule_applied` is exactly as on the finding: `ID@version` for a rule file, a bare ID for a completeness check. `layer` is the `Layer` name; `severity` is what the finding carries (`low` while the rule is unverified) |
| `strict` | The same for strict mode, the production default. Empty while every rule is unverified |
| `layers.R3_completeness` | What `CompletenessChecker` reports on its own, before `run_review` drops the ones a rule file already reported. Empty for a contract type with no checker |
| `layers.R4_R5_rules` | What `RuleEvaluator` reports on its own, with every rule in force on the contract's effective date |
| `gate_blocked_known_gaps` | Demo findings the Layer 5 gate blocks today because of a known gap, with the block reason. When the gap is fixed, delete the entry; the test will tell you when |

## How to add one

1. **Write the contract** with each defect planted deliberately and nothing else objectionable. Read the clause patterns in `app/rules/clauses.py` and the phrases in each rule file in `app/rules/rules/`, so an innocent sentence doesn't fire a rule by accident. For example, "pay a penalty of" anywhere fires ICA s.74, and any number above 45 followed by "days" after "pay" fires MSMED s.15 on vendor contracts.
2. **Write the intake file** by hand, as the model should answer. Give an `effective_date` on or after 2024-01-01, or the shipped rules won't be in force.
3. **Write the expected file from the planted defects**, before running anything. A file copied from the engine's output can only show the engine agrees with itself.
4. **Run `pytest tests/test_fixture_contracts.py`.** A failure is either a bug or a wrong expectation. Decide which; don't just copy what came out.

Remember while you do it:
- **A rule finding and a completeness finding for the same missing clause appear only once in `demo`**, as the rule's `@1` finding. Both still appear in `layers`.
- **Rules apply only to their `applies_to` types.** For example, the MSMED rules cover only `msa`, `sla` and `vendor_supplier`, and the completeness checker covers only `nda`.

## What is not covered yet

- **The DB-backed pipeline (R10).** `app.pipeline.runner` doesn't exist yet, so `test_full_pipeline_saves_exactly_the_expected_findings` is skipped. When R10 lands, it should save the findings in `strict` that pass the gate, and end in `pending_lawyer_review`.
- **R6, R7, R9.** No code yet, so no layer tests.
