"""R11 fixture contracts: synthetic contracts with planted defects and their expected findings.

Each fixture in tests/fixtures/contracts/ is three files (see the README there):
  <name>.txt                      the contract (invented companies only)
  <name>.intake.json              the intake LLM's canned output, so no real API is called
  <name>.expected_findings.json   every finding expected in demo mode and in strict mode, per layer

The chain tested here is the pipeline as far as it exists: R2 intake (mocked LLM) -> R3 completeness ->
R4/R5 rules, through run_review(), then the R8 gate on its own. The DB-backed pipeline (R10,
app.pipeline.runner) does not exist yet; its tests are at the bottom, skipped until it does.
"""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.agents.citation_gate import DocumentContext, StubFixtureCorpus, check_finding
from app.intake.service import IntakeService, clean_text
from app.rules import api
from app.rules.engine import RuleEvaluator
from app.rules.schema import RuleLoader, SkipReason, VerificationStatus
from app.schemas.finding import Finding
from app.schemas.normalized_document import NormalizedDocument

CONTRACTS = Path(__file__).parent / "fixtures" / "contracts"
FIXTURES = sorted(p.stem for p in CONTRACTS.glob("*.txt"))
FINDING_FIELDS = set(Finding.model_fields)


class CannedIntakeLLM:
    """Stands in for AsyncAnthropic: returns the fixture's canned extraction and records each request."""

    def __init__(self, extraction: dict):
        self.extraction = extraction
        self.requests = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    async def _create(self, **kwargs):
        self.requests.append(kwargs)
        return SimpleNamespace(stop_reason="end_turn",
                               content=[SimpleNamespace(type="text", text=json.dumps(self.extraction))])


def load(name: str) -> tuple[str, dict, dict]:
    text = (CONTRACTS / f"{name}.txt").read_text()
    intake = json.loads((CONTRACTS / f"{name}.intake.json").read_text())
    expected = json.loads((CONTRACTS / f"{name}.expected_findings.json").read_text())
    return text, intake, expected


def intake(name: str) -> NormalizedDocument:
    text, extraction, _ = load(name)
    return asyncio.run(IntakeService(CannedIntakeLLM(extraction)).normalize(text))


def review(name: str, *, strict: bool):
    """R2 -> R3 -> R4/R5, as the pipeline will run them: rules in force on the contract's effective date."""
    doc = intake(name)
    return asyncio.run(api.run_review(doc.full_text, doc.document_type.value, strict=strict,
                                      effective_date=doc.effective_date))


def triples(findings) -> list[dict]:
    return sorted(({"rule_applied": f.rule_applied, "layer": f.layer.name, "severity": f.severity.value}
                   for f in findings), key=lambda t: t["rule_applied"])


def expected_triples(entries: list[dict]) -> list[dict]:
    return sorted(entries, key=lambda t: t["rule_applied"])


def test_there_are_fixtures_and_each_has_all_three_files():
    assert FIXTURES == ["nda_bad", "nda_clean", "vendor_msme"]
    for name in FIXTURES:
        for suffix in (".intake.json", ".expected_findings.json"):
            assert (CONTRACTS / f"{name}{suffix}").is_file(), f"{name}{suffix} is missing"


# --- the chain, end to end --------------------------------------------------------------------

@pytest.mark.parametrize("name", FIXTURES)
def test_demo_mode_gives_exactly_the_expected_findings(name):
    # Exact match: a missing finding is a missed defect, an extra one is a false positive.
    assert triples(review(name, strict=False).findings) == expected_triples(load(name)[2]["demo"])


@pytest.mark.parametrize("name", FIXTURES)
def test_strict_mode_gives_exactly_the_expected_findings(name):
    result = review(name, strict=True)
    assert triples(result.findings) == expected_triples(load(name)[2]["strict"])
    # Nothing found because nothing ran, and the response says so.
    assert result.skipped_rules.count > 0
    assert any(s.reason is SkipReason.UNVERIFIED_IN_STRICT_MODE for s in result.skipped_rules.rules)


@pytest.mark.parametrize("name", FIXTURES)
def test_every_finding_is_a_valid_cited_finding(name):
    for f in review(name, strict=False).findings:
        assert f.citation and f.citation.strip() and f.citation_type is not None
        assert f.verification_status is VerificationStatus.UNVERIFIED
        Finding.model_validate(f.model_dump(include=FINDING_FIELDS))
        f.to_insert_row(f.finding_id, f.finding_id)          # the row would satisfy the table's checks


@pytest.mark.parametrize("name", FIXTURES)
def test_the_same_input_gives_identical_findings(name):
    # finding_id is a fresh uuid4 per run by design (it becomes findings.id); everything else must match.
    def run():
        return [f.model_dump(mode="json", exclude={"finding_id"}) for f in review(name, strict=False).findings]
    assert run() == run()


def test_the_clean_nda_gives_no_findings_in_either_mode():
    assert review("nda_clean", strict=False).findings == []
    assert review("nda_clean", strict=True).findings == []


def test_every_planted_defect_is_found_in_demo_mode():
    planted = found = 0
    for name in FIXTURES:
        _, _, expected = load(name)
        reported = {f.rule_applied.split("@")[0] for f in review(name, strict=False).findings}
        for defect in expected["planted_defects"]:
            planted += 1
            found += defect["rule_id"] in reported
    assert (found, planted) == (6, 6)


# --- one layer at a time ----------------------------------------------------------------------

@pytest.mark.parametrize("name", FIXTURES)
def test_layer_r2_intake(name):
    text, extraction, expected = load(name)
    llm = CannedIntakeLLM(extraction)
    doc = asyncio.run(IntakeService(llm).normalize(text))
    assert len(llm.requests) == 1                                   # one call, no retries
    assert doc.document_type.value == expected["contract_type"]
    assert doc.full_text == clean_text(text)
    assert [c.value for c in doc.clauses] == list(dict.fromkeys(extraction["clauses"]))


@pytest.mark.parametrize("name", FIXTURES)
def test_layer_r3_completeness(name):
    text, _, expected = load(name)
    checker = api._checkers().get(expected["contract_type"])
    found = sorted(f.rule_applied for f in checker.check(text)) if checker else []
    assert found == sorted(expected["layers"]["R3_completeness"])


@pytest.mark.parametrize("name", FIXTURES)
def test_layer_r4_r5_rules(name):
    text, _, expected = load(name)
    day = intake(name).effective_date
    rules = RuleLoader(api.RULES_DIR, strict=False, on=day).load()
    found = sorted(f.rule_applied for f in RuleEvaluator(rules, today=day).evaluate(text, expected["contract_type"]))
    assert found == sorted(expected["layers"]["R4_R5_rules"])


@pytest.mark.parametrize("name", FIXTURES)
def test_layer_r8_citation_gate(name):
    # Records what the Layer 5 gate blocks today. Each entry in gate_blocked_known_gaps is a known gap
    # (see the R8 task list); when one is fixed, remove it from the fixture's expected file.
    _, _, expected = load(name)
    doc = intake(name)
    blocked = []
    for f in review(name, strict=False).findings:
        decision = check_finding(f, StubFixtureCorpus(), DocumentContext(doc_type=doc.document_type.value))
        if not decision.allowed:
            blocked.append({"rule_applied": f.rule_applied, "reason": decision.reason.value})
    known = [{"rule_applied": g["rule_applied"], "reason": g["reason"]} for g in expected["gate_blocked_known_gaps"]]
    assert sorted(blocked, key=str) == sorted(known, key=str)


# R6 (cross-clause consistency), R7 (risk asymmetry) and R9 (triage) have no code yet: nothing to test.


# --- the DB-backed pipeline (R10) -------------------------------------------------------------

_NO_RUNNER = "needs app.pipeline.runner.run_pipeline from pipeline-r10, which is not built yet"


@pytest.mark.skip(reason=_NO_RUNNER)
@pytest.mark.parametrize("name", FIXTURES)
def test_full_pipeline_saves_exactly_the_expected_findings(name):
    """TODO(R10): run run_pipeline(document_id, version_id) with the canned intake LLM and a mocked
    database, then assert: the saved agent findings equal what passes the gate out of
    expected["strict"] (production runs strict); the document ends in pending_lawyer_review; a
    second run replaces the version's agent findings and keeps lawyer-added ones."""
