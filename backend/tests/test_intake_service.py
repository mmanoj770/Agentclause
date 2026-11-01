import asyncio
import json
import os
from datetime import date
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.auth.dependencies import CurrentUser, get_current_user
from app.intake.router import get_service
from app.intake.service import (ExtractionFailedError, IntakeError, IntakeNotConfiguredError, IntakeService,
                                NotAContractError, clean_text)
from app.schemas.normalized_document import NormalizedDocument

NDA_TEXT = """
CONFIDENTIALITY AGREEMENT

This Confidentiality Agreement is entered into as of 15th October, 2026
between ACME Corporation, a company incorporated in India ("Discloser")
and XYZ Startup Private Limited, registered in Bangalore ("Recipient").

1. CONFIDENTIAL INFORMATION
Recipient shall maintain confidentiality of all disclosed information.

2. DEFINITION
Confidential Information means any information disclosed by Discloser.

3. GOVERNING LAW
This Agreement shall be governed by the laws of India.

4. TERM
This Agreement shall remain in effect for 2 years.

5. RETURN OF DOCUMENTS
Recipient shall return all documents upon termination.
"""

EMPLOYMENT_TEXT = """
EMPLOYMENT AGREEMENT

This Agreement is between ABC Ltd and Rajesh Kumar, effective 1 November 2026.

1. POSITION: Software Engineer
2. REMUNERATION: Rs 50,000 per month
3. CONFIDENTIALITY: All company information is confidential
4. NON-COMPETE: Employee cannot compete for 2 years after employment ends
5. JURISDICTION: This is governed by Maharashtra law
"""

NDA_EXTRACTION = {
    "is_contract": True,
    "parties": ["ACME Corporation", "XYZ Startup Private Limited"],
    "execution_date": "2026-10-15",
    "effective_date": None,
    "document_type": "nda",
    "jurisdiction": "India",
    "clauses": ["confidentiality", "confidential_info_definition", "governing_law", "term", "return_destruction"],
}


class FakeClient:
    """Stands in for AsyncAnthropic: returns queued extractions and records each request."""

    def __init__(self, *outputs, stop_reason="end_turn"):
        self.outputs = list(outputs)
        self.stop_reason = stop_reason
        self.requests = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    async def _create(self, **kwargs):
        self.requests.append(kwargs)
        text = json.dumps(self.outputs.pop(0)) if self.outputs else "{}"
        return SimpleNamespace(stop_reason=self.stop_reason,
                               content=[SimpleNamespace(type="text", text=text)])


def normalize(client, text=NDA_TEXT, **kw):
    return asyncio.run(IntakeService(client).normalize(text, **kw))


# --- model ------------------------------------------------------------------------------------

def test_normalized_document_validation():
    doc = NormalizedDocument(parties=["Party A", "Party B"], execution_date=date(2026, 10, 15),
                             document_type="nda", jurisdiction="India",
                             clauses=["confidentiality", "governing_law"], full_text="Test contract")
    assert doc.extraction_confidence is None


@pytest.mark.parametrize("change", [
    {"parties": ["Party A"]},
    {"parties": ["Party A", "party a"]},          # not two distinct parties
    {"parties": ["Party A", "  "]},
    {"clauses": []},
    {"clauses": ["made_up_clause"]},
    {"document_type": "vendor_agreement"},        # not a contract_types code
    {"execution_date": "15/10/2026"},
    {"extraction_confidence": 1.5},
    {"full_text": ""},
])
def test_normalized_document_rejects(change):
    base = {"parties": ["A", "B"], "document_type": "nda", "clauses": ["confidentiality"], "full_text": "x"}
    with pytest.raises(ValidationError):
        NormalizedDocument(**{**base, **change})


def test_duplicate_clauses_removed():
    doc = NormalizedDocument(parties=["A", "B"], document_type="nda", full_text="x",
                             clauses=["term", "confidentiality", "term"])
    assert [c.value for c in doc.clauses] == ["term", "confidentiality"]


def test_normalized_document_example():
    example = NormalizedDocument.model_config["json_schema_extra"]["example"]
    doc = NormalizedDocument(**example)
    assert doc.parties == ["ACME Corp", "XYZ Startup Private Limited"] and doc.document_type.value == "nda"


def test_clean_text():
    raw = "﻿CLAUSE 1.\r\n  The   Recipient​ shall\x07 keep it.\r\n\r\n\r\n\r\n2. Term.  "
    assert clean_text(raw) == "CLAUSE 1.\nThe Recipient shall keep it.\n\n2. Term."


# --- service ----------------------------------------------------------------------------------

def test_normalize_nda():
    client = FakeClient(NDA_EXTRACTION)
    doc = normalize(client)
    assert doc.parties == ["ACME Corporation", "XYZ Startup Private Limited"]
    assert doc.document_type.value == "nda" and doc.jurisdiction == "India"
    assert doc.execution_date == date(2026, 10, 15) and doc.effective_date is None
    assert doc.full_text == clean_text(NDA_TEXT)
    assert len(client.requests) == 1


def test_request_shape():
    client = FakeClient(NDA_EXTRACTION)
    normalize(client)
    req = client.requests[0]
    assert req["model"] == "claude-opus-5-5"
    assert req["output_config"]["format"]["type"] == "json_schema"
    assert req["fallbacks"] == "default" and req["betas"] == ["server-side-fallback-2026-07-01"]
    content = req["messages"][0]["content"]
    assert content.startswith("<contract>\n") and content.endswith("\n</contract>")


def test_invalid_extraction_is_retried_with_the_error_as_feedback():
    one_party = {**NDA_EXTRACTION, "parties": ["ACME Corporation"]}
    client = FakeClient(one_party, NDA_EXTRACTION)
    doc = normalize(client)
    assert len(doc.parties) == 2 and len(client.requests) == 2
    assert "parties" in client.requests[1]["messages"][0]["content"]


def test_gives_up_after_max_attempts():
    one_party = {**NDA_EXTRACTION, "parties": ["ACME Corporation"]}
    client = FakeClient(one_party, one_party)
    with pytest.raises(ExtractionFailedError, match="after 2 attempts"):
        normalize(client, max_attempts=2)
    assert len(client.requests) == 2


def test_not_a_contract_fails_without_retrying():
    client = FakeClient({**NDA_EXTRACTION, "is_contract": False, "parties": [], "clauses": []})
    with pytest.raises(NotAContractError):
        normalize(client, "This is just random text, not a contract at all")
    assert len(client.requests) == 1


def test_empty_text_never_calls_the_model():
    client = FakeClient()
    with pytest.raises(NotAContractError):
        normalize(client, " \n​ ")
    assert client.requests == []


@pytest.mark.parametrize("stop_reason", ["refusal", "max_tokens"])
def test_unusable_stop_reasons_raise(stop_reason):
    with pytest.raises(IntakeError):
        normalize(FakeClient(NDA_EXTRACTION, stop_reason=stop_reason))


def test_missing_credentials_is_a_clear_error(monkeypatch):
    for var in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_PROFILE"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("HOME", "/nonexistent")  # no `ant auth login` profile either
    import anthropic
    with pytest.raises(IntakeNotConfiguredError):
        normalize(anthropic.AsyncAnthropic(max_retries=0))


# --- endpoint ---------------------------------------------------------------------------------

@pytest.fixture
def as_user():
    from app.main import app
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(id="u", email=None, role="startup_user", org_id=None)
    yield app
    app.dependency_overrides.clear()


def test_endpoint_returns_normalized_document(client, as_user):
    as_user.dependency_overrides[get_service] = lambda: IntakeService(FakeClient(NDA_EXTRACTION))
    r = client.post("/intake/normalize", json={"contract_text": NDA_TEXT})
    assert r.status_code == 200
    assert r.json()["document_type"] == "nda" and r.json()["execution_date"] == "2026-10-15"


def test_endpoint_not_a_contract_is_422(client, as_user):
    as_user.dependency_overrides[get_service] = lambda: IntakeService(
        FakeClient({**NDA_EXTRACTION, "is_contract": False}))
    assert client.post("/intake/normalize", json={"contract_text": "hello"}).status_code == 422


def test_endpoint_requires_login(client):
    r = client.post("/intake/normalize", json={"contract_text": NDA_TEXT})
    assert r.status_code in (401, 403)


# --- live (real Claude API; skipped without a key, costs a few cents per run) -----------------

live = pytest.mark.skipif(not os.environ.get("ANTHROPIC_API_KEY"), reason="ANTHROPIC_API_KEY not set")


@live
def test_live_normalize_nda():
    doc = asyncio.run(IntakeService().normalize(NDA_TEXT))
    assert len(doc.parties) >= 2 and doc.document_type.value == "nda"
    assert doc.jurisdiction == "India" and doc.execution_date == date(2026, 10, 15)
    assert {"confidentiality", "governing_law"} <= {c.value for c in doc.clauses}


@live
def test_live_normalize_employment():
    doc = asyncio.run(IntakeService().normalize(EMPLOYMENT_TEXT))
    assert doc.document_type.value == "employment_contract"
    assert {"non_compete", "remuneration"} <= {c.value for c in doc.clauses}


@live
def test_live_not_a_contract():
    with pytest.raises(NotAContractError):
        asyncio.run(IntakeService().normalize("This is just random text, not a contract at all"))
