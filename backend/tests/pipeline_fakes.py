"""Fakes for the R10 pipeline tests: an in-memory database, the gate's audit connection, and canned intake.

FakeDB answers exactly the SQL the pipeline sends and fails on anything else. Its transaction() rolls the
findings and the document back on an exception, as Postgres would. fake_transition enforces the real
state machine (app.documents.states.TRANSITIONS), so a test cannot pass by making an illegal move.
"""
import asyncio
import copy
import json
import uuid
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

from fastapi import HTTPException

from app.documents.states import TRANSITIONS, DocState
from app.intake.service import IntakeService
from app.schemas.finding import INSERT_COLUMNS

CONTRACTS = Path(__file__).parent / "fixtures" / "contracts"


class Result:
    def __init__(self, rows):
        self.rows = rows

    def fetchone(self):
        return self.rows[0] if self.rows else None


class FakeDB:
    def __init__(self, doc_type="nda", state="under_ai_review"):
        self.doc = {"id": uuid.uuid4(), "doc_type": doc_type, "state": state, "triage_tier": None}
        self.version_id = uuid.uuid4()
        self.findings: list[dict] = []
        self.audit: list[dict] = []
        self.moves: list[str] = []
        self.commits = self.rollbacks = 0
        self.fail_on_insert = False

    @contextmanager
    def transaction(self):
        saved = copy.deepcopy((self.doc, self.findings, self.audit, self.moves))
        try:
            yield self
        except BaseException:
            self.doc, self.findings, self.audit, self.moves = saved
            raise

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def execute(self, sql, params=()):
        s = " ".join(sql.split())
        if s.startswith("select doc_type, state from documents where id"):
            return Result([self.doc] if params[0] == self.doc["id"] else [])
        if s.startswith("delete from findings where document_version_id = %s and coalesce(advocate_action, '') <> 'add'"):
            self.findings = [f for f in self.findings
                             if not (f["document_version_id"] == params[0] and f["advocate_action"] != "add")]
            return Result([])
        if s.startswith("select 1 from document_versions where id = %s and document_id = %s"):
            return Result([{"?column?": 1}] if (params[0], params[1]) == (self.version_id, self.doc["id"]) else [])
        if s.startswith("insert into findings"):
            if self.fail_on_insert:
                raise RuntimeError("database went away")
            self.findings.append(dict(zip(INSERT_COLUMNS, params)))
            return Result([])
        if s.startswith("update documents set triage_tier"):
            self.doc["triage_tier"] = params[0]
            return Result([])
        if s.startswith("insert into audit_logs"):
            self.audit.append({"action": params[3], "details": params[4].obj})
            return Result([])
        raise AssertionError(f"unexpected SQL: {s}")

    def actions(self) -> list[str]:
        return [a["action"] for a in self.audit]

    def agent_findings(self) -> list[dict]:
        return [f for f in self.findings if f["advocate_action"] != "add"]


def fake_transition(db: FakeDB):
    """transition() for FakeDB, checked against the real TRANSITIONS table."""
    def transition(conn, doc_id, to_state, actor, note=None):
        allowed = TRANSITIONS.get((DocState(db.doc["state"]), to_state))
        if allowed is None:
            raise HTTPException(409, f"Cannot move from '{db.doc['state']}' to '{to_state.value}'")
        if actor.kind not in allowed:
            raise HTTPException(403, "Your role cannot make this change")
        db.audit.append({"action": "state_change", "details": {"from": db.doc["state"], "to": to_state.value}})
        db.doc["state"] = to_state.value
        db.moves.append(to_state.value)
        return db.doc
    return transition


class GateAudit:
    """The citation gate writes audit rows on its own connection; this records them."""
    def __init__(self):
        self.rows = []

    @contextmanager
    def connection(self):
        outer = self

        class C:
            @contextmanager
            def transaction(s):
                yield s

            def execute(s, sql, params=()):
                outer.rows.append({"action": params[3], "details": params[4].obj})
        yield C()


class CannedIntakeLLM:
    """Stands in for AsyncAnthropic in IntakeService: returns the fixture's canned extraction."""
    def __init__(self, extraction: dict):
        self.extraction = extraction
        self.calls = 0
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    async def _create(self, **kwargs):
        self.calls += 1
        return SimpleNamespace(stop_reason="end_turn",
                               content=[SimpleNamespace(type="text", text=json.dumps(self.extraction))])


def fixture_text(name: str) -> str:
    return (CONTRACTS / f"{name}.txt").read_text()


def canned_normalise(name: str):
    """A normalise() for PipelineDeps that runs the real IntakeService against the fixture's canned LLM output."""
    extraction = json.loads((CONTRACTS / f"{name}.intake.json").read_text())

    def normalise(text):
        return asyncio.run(IntakeService(CannedIntakeLLM(extraction)).normalize(text))
    return normalise


@contextmanager
def connection_to(db: FakeDB):
    yield db
