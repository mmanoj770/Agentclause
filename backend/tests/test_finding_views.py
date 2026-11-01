"""Lawyer findings views (agent / advocate read models, origin) and the finding_id / id alias."""
import uuid
from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import CurrentUser, get_current_user
from app.db import get_conn
from app.findings import schemas
from app.findings.schemas import (ID_ALIAS_UNTIL, AdvocateFindingOut, AgentFindingOut, ClientFindingOut,
                                  lawyer_finding_out)
from app.main import app

ORG_A = str(uuid.uuid4())
DOC = str(uuid.uuid4())
LAWYER = str(uuid.uuid4())
OTHER_LAWYER = str(uuid.uuid4())


def agent_row(action=None, status="pending", **extra):
    base = {"id": uuid.uuid4(), "layer": 2, "severity": "high", "clause_reference": "Clause 3.1",
            "description": "agent issue", "rule_applied": "NDA_GOVERNING_LAW_MISSING",
            "remedy_suggested": "fix", "citation": "Indian Contract Act, 1872, s. 27",
            "citation_type": "STATUTORY", "advocate_action": action, "advocate_notes": None,
            "adjudicated_at": None, "status": status, "version_no": 1}
    base.update(extra)
    return base


def advocate_row(**extra):
    base = {"id": uuid.uuid4(), "layer": None, "severity": "medium", "clause_reference": "Clause 9",
            "description": "lawyer's own point", "rule_applied": None, "remedy_suggested": None,
            "citation": None, "citation_type": None, "advocate_action": "add",
            "advocate_notes": "my note", "adjudicated_at": datetime.now(timezone.utc), "status": "added",
            "version_no": 1}
    base.update(extra)
    return base


# --- the id alias ---------------------------------------------------------------------------------

def test_every_finding_model_carries_id_as_an_alias_of_finding_id():
    a = lawyer_finding_out(agent_row())
    b = lawyer_finding_out(advocate_row())
    c = ClientFindingOut(finding_id=uuid.uuid4(), severity="low", description="x", status="confirmed",
                         origin="agent")
    for m in (a, b, c):
        dumped = m.model_dump(mode="json")
        assert dumped["id"] == dumped["finding_id"] == str(m.finding_id)


def test_the_id_alias_is_removed_after_the_integration_day():
    assert date.today() <= ID_ALIAS_UNTIL, (
        f"The deprecated `id` alias was due for removal after {ID_ALIAS_UNTIL}. Remove the `id` "
        "property from _FindingId in app/findings/schemas.py and the alias assertions in the tests.")


# --- read models ----------------------------------------------------------------------------------

def test_agent_finding_view_names_the_layer_and_keeps_the_citation():
    v = lawyer_finding_out(agent_row())
    assert isinstance(v, AgentFindingOut)
    d = v.model_dump(mode="json")
    assert d["origin"] == "agent" and d["layer"] == "STATUTORY" and d["citation_type"] == "STATUTORY"
    assert d["status"] == "pending"


def test_lawyer_added_finding_is_its_own_model_without_layer_or_citation():
    v = lawyer_finding_out(advocate_row())
    assert isinstance(v, AdvocateFindingOut)
    d = v.model_dump(mode="json")
    assert d["origin"] == "advocate" and d["status"] == "added"
    for absent in ("layer", "citation", "citation_type"):
        assert absent not in d


def test_origin_comes_from_the_lawyers_action_not_from_the_row_content():
    # A row that claims origin=advocate and carries layer data, but was not added by a lawyer.
    spoof = agent_row(action="confirm", status="confirmed", origin="advocate")
    assert lawyer_finding_out(spoof).origin == "agent"
    # An added finding stays advocate even if the row has a layer and a citation.
    assert lawyer_finding_out(advocate_row(layer=2, citation="x", citation_type="STATUTORY")).origin == "advocate"


def test_a_damaged_old_agent_row_with_no_layer_still_renders():
    v = lawyer_finding_out(agent_row(layer=None, citation=None, citation_type=None))
    assert v.layer is None and v.citation is None


# --- routes ---------------------------------------------------------------------------------------

class Result:
    def __init__(self, rows):
        self.rows = rows

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


class FakeConn:
    def __init__(self, rows=None, doc_state="pending_lawyer_review", finding=None):
        self.doc = {"id": uuid.UUID(DOC), "org_id": ORG_A, "assigned_lawyer_id": LAWYER, "state": doc_state}
        self.rows = rows or []
        self.finding = finding
        self.updates, self.audit, self.inserts, self.sql = [], [], [], []

    def transaction(self):
        class Tx:
            def __enter__(s): return s
            def __exit__(s, *a): return False
        return Tx()

    def execute(self, sql, params=()):
        s = " ".join(sql.split())
        self.sql.append(s)
        if s.startswith("select * from documents where id") and "for update" in s:
            return Result([self.doc])
        if s.startswith("select * from documents where id"):
            return Result([self.doc] if str(params[0]) == DOC else [])
        if s.startswith("select f.id, f.layer"):
            return Result(self.rows)
        if s.startswith("select f.*, d.state as doc_state"):
            return Result([self.finding] if self.finding else [])
        if s.startswith("update findings set advocate_action"):
            self.updates.append(params)
            return Result([{**self.finding, "advocate_action": params[0], "advocate_notes": params[1],
                            "status": "confirmed" if params[0] == "confirm" else "overridden"}])
        if s.startswith("select id from document_versions"):
            return Result([{"id": uuid.uuid4()}])
        if s.startswith("insert into findings"):
            self.inserts.append(params)
            return Result([advocate_row(description=params[4])])
        if s.startswith("insert into audit_logs"):
            self.audit.append(params)
            return Result([])
        raise AssertionError(f"unexpected SQL: {s}")


@pytest.fixture
def env():
    conn = FakeConn()
    state = {"user": CurrentUser(id=LAWYER, email=None, role="lawyer", org_id=None)}
    app.dependency_overrides[get_current_user] = lambda: state["user"]
    app.dependency_overrides[get_conn] = lambda: conn
    yield type("Env", (), {"client": TestClient(app), "conn": conn, "state": state})
    app.dependency_overrides.clear()


def test_lawyer_list_is_one_merged_list_tagged_by_origin(env):
    env.conn.rows = [agent_row(), advocate_row()]
    r = env.client.get(f"/documents/{DOC}/findings")
    assert r.status_code == 200
    body = r.json()
    assert [f["origin"] for f in body] == ["agent", "advocate"]
    assert all(f["id"] == f["finding_id"] for f in body)
    assert "layer" in body[0] and "layer" not in body[1]


def test_lawyer_list_query_names_its_columns(env):
    env.client.get(f"/documents/{DOC}/findings")
    q = next(x for x in env.conn.sql if x.startswith("select f.id, f.layer"))
    assert "f.*" not in q and "max(version_no)" in q


def test_lawyer_list_is_404_for_an_unassigned_lawyer(env):
    env.state["user"] = CurrentUser(id=OTHER_LAWYER, email=None, role="lawyer", org_id=None)
    assert env.client.get(f"/documents/{DOC}/findings").status_code == 404


def test_adjudicate_returns_the_agent_view_with_both_ids(env):
    fid = uuid.uuid4()
    env.conn.finding = {**agent_row(), "id": fid, "document_id": uuid.UUID(DOC),
                        "doc_state": "pending_lawyer_review", "assigned_lawyer_id": LAWYER}
    r = env.client.post(f"/findings/{fid}/adjudicate", json={"action": "confirm"})
    assert r.status_code == 200
    body = r.json()
    assert body["origin"] == "agent" and body["finding_id"] == body["id"] == str(fid)
    assert body["status"] == "confirmed"


def test_a_lawyer_added_finding_cannot_be_adjudicated(env):
    """Adjudicating would overwrite 'add' and flip the finding to origin=agent."""
    fid = uuid.uuid4()
    env.conn.finding = {**advocate_row(), "id": fid, "document_id": uuid.UUID(DOC),
                        "doc_state": "pending_lawyer_review", "assigned_lawyer_id": LAWYER}
    r = env.client.post(f"/findings/{fid}/adjudicate", json={"action": "override", "notes": "no"})
    assert r.status_code == 409
    assert env.conn.updates == []


def test_adding_a_finding_returns_the_advocate_view(env):
    r = env.client.post(f"/documents/{DOC}/findings",
                        json={"severity": "medium", "description": "my point"})
    assert r.status_code == 201
    body = r.json()
    assert body["origin"] == "advocate" and body["status"] == "added"
    assert body["id"] == body["finding_id"]
    assert "layer" not in body and "citation" not in body
