"""Intake normalisation (R2). The Gemini call is replaced by a stand-in: no unit test reaches a real API.
The one live test is marked `live` and runs only with RUN_LIVE_TESTS=1 and a GEMINI_API_KEY."""
import asyncio
import json
import logging
import os
from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from app import gemini
from app.auth.dependencies import CurrentUser, get_current_user
from app.config import settings
from app.intake import service
from app.intake.service import (ExtractionFailedError, IntakeError, IntakeNotConfiguredError,
                                IntakeUnavailableError, NotAContractError, clean_text, normalize)
from app.rules.api import run_review, run_review_normalized
from app.rules.clauses import CLAUSES
from app.schemas.normalized_document import ClauseType, NormalizedDocument

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

5. CARVE-OUT
Information already known to everyone is outside this Agreement.
"""

PARTIES = ["ACME Corporation", "XYZ Startup Private Limited"]

CLAUSES_OUT = [
    {"clause_number": "1", "heading": "CONFIDENTIAL INFORMATION", "clause_type": "confidentiality",
     "text": "Recipient shall maintain confidentiality of all disclosed information."},
    {"clause_number": "2", "heading": "DEFINITION", "clause_type": "confidential-info-definition",
     "text": "Confidential Information means any information disclosed by Discloser."},
    {"clause_number": "3", "heading": "GOVERNING LAW", "clause_type": "governing-law",
     "text": "This Agreement shall be governed by the laws of India."},
    {"clause_number": "4", "heading": "TERM", "clause_type": "term",
     "text": "This Agreement shall remain in effect for 2 years."},
    {"clause_number": "5", "heading": "CARVE-OUT", "clause_type": "exclusions",
     "text": "Information already known to everyone is outside this Agreement."},
]

VALID = {
    "is_contract": True,
    "parties": PARTIES,
    "execution_date": "2026-10-15",
    "effective_date": None,
    "jurisdiction": "India",
    "clauses": CLAUSES_OUT,
}

INVENTED = {"clause_number": "6", "heading": "RESIDUALS", "clause_type": "residuals",
            "text": "Residual knowledge retained in unaided memory may be used freely."}


class FakeGemini:
    """Stands in for gemini.generate_json: returns (or raises) the scripted answers in order."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.prompts: list[str] = []
        self.models: list[str] = []

    def __call__(self, prompt, *, system, model=None, timeout=60):
        self.prompts.append(prompt)
        self.models.append(model)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")

    def install(*answers):
        f = FakeGemini(*answers)
        monkeypatch.setattr(gemini, "generate_json", f)
        return f
    return install


# --- schema ----------------------------------------------------------------------------------------

def test_clause_types_are_the_completeness_checker_ids():
    required = json.loads((Path(__file__).parents[1] / "app/rules/config/nda_required_clauses.json").read_text())
    values = {c.value for c in ClauseType}
    assert values == set(CLAUSES) | {"other"}
    assert {r["clause"] for r in required["required"]} <= values


def doc(**change):
    return NormalizedDocument.model_validate({
        "parties": PARTIES, "document_type": "nda", "clauses": CLAUSES_OUT[:1], "full_text": "x",
        "extraction_model": "m", "extraction_attempts": 1, **change})


def test_normalized_document_valid():
    d = doc(execution_date="2026-10-15")
    assert d.execution_date == date(2026, 10, 15)
    assert d.clause_types() == {"confidentiality"}


@pytest.mark.parametrize("change", [
    {"parties": ["ACME Corporation"]},                 # fewer than 2 parties
    {"parties": ["ACME", "acme"]},                     # not 2 distinct parties
    {"parties": ["ACME", ""]},
    {"document_type": "other"},                        # not a contract_types code
    {"clauses": []},
    {"clauses": [{**CLAUSES_OUT[0], "clause_type": "non_compete"}]},
    {"extraction_attempts": 0},
])
def test_normalized_document_rejects(change):
    with pytest.raises(ValidationError):
        doc(**change)


def test_clean_text():
    assert clean_text("A​  b\r\n\r\n\r\n\r\nc\x07 ") == "A b\n\nc"


# --- normalize -------------------------------------------------------------------------------------

def test_valid_nda(fake):
    f = fake(VALID)
    d = normalize(NDA_TEXT, "nda")
    assert d.parties == PARTIES
    assert d.execution_date == date(2026, 10, 15) and d.effective_date is None
    assert d.document_type.value == "nda" and d.jurisdiction == "India"
    assert [c.clause_type.value for c in d.clauses] == [c["clause_type"] for c in CLAUSES_OUT]
    assert all(c.text in d.full_text for c in d.clauses)
    assert d.extraction_attempts == 1
    assert d.extraction_model == settings.gemini_intake_model == f.models[0]
    assert "<contract>" in f.prompts[0]


def test_invalid_json_then_success(fake):
    f = fake(gemini.GeminiError("Gemini did not return valid JSON"), VALID)
    d = normalize(NDA_TEXT, "nda")
    assert d.extraction_attempts == 2
    assert "not a single valid JSON object" in f.prompts[1]


def test_schema_invalid_then_success_with_error_fed_back(fake):
    f = fake({**VALID, "execution_date": "15/10/2026"}, VALID)
    d = normalize(NDA_TEXT, "nda")
    assert d.extraction_attempts == 2
    assert "rejected" not in f.prompts[0]
    assert "execution_date" in f.prompts[1]


def test_three_failures_raise_intake_error(fake):
    f = fake({"parties": PARTIES}, gemini.GeminiError("Gemini did not return valid JSON"), {**VALID, "clauses": "x"})
    with pytest.raises(ExtractionFailedError, match="after 3 attempts") as exc:
        normalize(NDA_TEXT, "nda")
    assert isinstance(exc.value, IntakeError)
    assert len(f.prompts) == 3


def test_fewer_than_two_parties_rejected(fake):
    f = fake(*[{**VALID, "parties": ["ACME Corporation"]}] * 3)
    with pytest.raises(ExtractionFailedError, match="parties"):
        normalize(NDA_TEXT, "nda")
    assert "parties" in f.prompts[1]


def test_invented_clause_text_is_dropped_and_counted(fake, caplog):
    fake({**VALID, "clauses": CLAUSES_OUT + [INVENTED]})
    with caplog.at_level(logging.INFO, logger=service.logger.name):
        d = normalize(NDA_TEXT, "nda")
    assert INVENTED["text"] not in [c.text for c in d.clauses]
    assert len(d.clauses) == len(CLAUSES_OUT)
    assert "dropped 1 of 6 clause(s)" in caplog.text


def test_paraphrased_clause_is_dropped(fake):
    paraphrase = {**CLAUSES_OUT[2], "text": "This Agreement is governed by the laws of India."}
    fake({**VALID, "clauses": [paraphrase, CLAUSES_OUT[0]]})
    d = normalize(NDA_TEXT, "nda")
    assert [c.clause_type.value for c in d.clauses] == ["confidentiality"]


def test_all_clauses_invented_is_retried(fake):
    f = fake({**VALID, "clauses": [INVENTED]}, VALID)
    assert normalize(NDA_TEXT, "nda").extraction_attempts == 2
    assert "copy it exactly" in f.prompts[1]


def test_logs_hold_no_contract_text_or_parties(fake, caplog):
    fake({**VALID, "execution_date": "bad"}, {**VALID, "clauses": CLAUSES_OUT + [INVENTED]})
    with caplog.at_level(logging.DEBUG, logger=service.logger.name):
        normalize(NDA_TEXT, "nda")
    for secret in PARTIES + [c["text"] for c in CLAUSES_OUT] + [INVENTED["text"], "bad"]:
        assert secret not in caplog.text


def test_not_a_contract_fails_without_retrying(fake):
    f = fake({"is_contract": False})
    with pytest.raises(NotAContractError):
        normalize("Shopping list: milk, eggs.", "nda")
    assert len(f.prompts) == 1


def test_empty_text_never_calls_the_model(fake):
    f = fake()
    with pytest.raises(NotAContractError):
        normalize(" ​\n ", "nda")
    assert f.prompts == []


def test_unknown_contract_type(fake):
    with pytest.raises(IntakeError, match="Unknown contract type"):
        normalize(NDA_TEXT, "other")


def test_missing_key_is_not_configured(fake, monkeypatch):
    fake(gemini.GeminiError("GEMINI_API_KEY is not set."))
    monkeypatch.setattr(settings, "gemini_api_key", "")
    with pytest.raises(IntakeNotConfiguredError):
        normalize(NDA_TEXT, "nda")


def test_api_failure_is_unavailable_without_retrying(fake):
    f = fake(gemini.GeminiError("Gemini m:generateContent failed - HTTP 503: overloaded"))
    with pytest.raises(IntakeUnavailableError):
        normalize(NDA_TEXT, "nda")
    assert len(f.prompts) == 1


# --- review adapter --------------------------------------------------------------------------------

def test_run_review_normalized_uses_intake_clauses(fake):
    fake(VALID)
    d = normalize(NDA_TEXT, "nda")
    by_text = {f.rule_applied for f in asyncio.run(run_review(d.full_text, "nda", strict=False)).findings}
    by_doc = {f.rule_applied for f in asyncio.run(run_review_normalized(d, strict=False)).findings}
    # Clause 5's wording escapes the keyword patterns; intake labelled it, so it is not reported missing.
    assert "NDA_EXCLUSIONS_MISSING" in by_text
    assert "NDA_EXCLUSIONS_MISSING" not in by_doc
    assert by_doc == by_text - {"NDA_EXCLUSIONS_MISSING"}


# --- endpoint --------------------------------------------------------------------------------------

BODY = {"contract_text": NDA_TEXT, "contract_type_id": "nda"}


@pytest.fixture
def as_user(client):
    def login(role="startup_user", org_id="org-1"):
        client.app.dependency_overrides[get_current_user] = lambda: CurrentUser(
            id="u", email=None, role=role, org_id=org_id)
    yield login
    client.app.dependency_overrides.clear()


def test_endpoint_requires_login(client):
    assert client.post("/intake/normalize", json=BODY).status_code == 401


def test_endpoint_returns_normalized_document(client, as_user, fake):
    fake(VALID)
    as_user()
    r = client.post("/intake/normalize", json=BODY)
    assert r.status_code == 200
    assert r.json()["parties"] == PARTIES and r.json()["clauses"][2]["clause_type"] == "governing-law"


def test_endpoint_startup_without_org_is_400(client, as_user, fake):
    f = fake()
    as_user(org_id=None)
    assert client.post("/intake/normalize", json=BODY).status_code == 400
    assert f.prompts == []


@pytest.mark.parametrize("body", [{"contract_text": NDA_TEXT}, {**BODY, "contract_type_id": "other"},
                                  {**BODY, "contract_text": ""}])
def test_endpoint_rejects_bad_body(client, as_user, body):
    as_user()
    assert client.post("/intake/normalize", json=body).status_code == 422


def test_endpoint_text_must_be_in_the_body_not_the_query(client, as_user):
    as_user()
    assert client.post("/intake/normalize", params=BODY).status_code == 422


@pytest.mark.parametrize("answer,status", [
    ({"is_contract": False}, 422),
    (gemini.GeminiError("Gemini m:generateContent failed - HTTP 503"), 503),
])
def test_endpoint_errors(client, as_user, fake, answer, status):
    fake(answer)
    as_user()
    r = client.post("/intake/normalize", json=BODY)
    assert r.status_code == status and "Traceback" not in r.text


def test_endpoint_extraction_failure_is_502_not_500(client, as_user, fake):
    fake(*[{"parties": PARTIES}] * 3)
    as_user()
    assert client.post("/intake/normalize", json=BODY).status_code == 502


# --- live (real Gemini call; off by default) -------------------------------------------------------

@pytest.mark.live
@pytest.mark.skipif(not (os.environ.get("RUN_LIVE_TESTS") == "1" and settings.gemini_api_key),
                    reason="live test: set RUN_LIVE_TESTS=1 and GEMINI_API_KEY")
def test_live_normalize_nda():
    d = normalize(NDA_TEXT, "nda")
    assert len(d.parties) >= 2
    assert {"confidentiality", "governing-law"} <= d.clause_types()


# --- Task 3: DPDP PII Redaction & Restoration Tests --------------------------------------------

PII_TEXT = """
SERVICES AGREEMENT

This Agreement is made by Acme Corp (PAN: ABCDE1234F, GSTIN: 27ABCDE1234F1Z5, Email: contact@acme.com)
and Rahul Sharma (Aadhaar: 2345 6789 0123, Phone: +91 9876543210).
Payment shall be made to Account: 123456789012, IFSC: HDFC0001234.
Repeated PAN: ABCDE1234F for tax purposes.

1. PAYMENT
The client shall wire funds to Account: 123456789012 at IFSC: HDFC0001234.

2. NOTICES
Notices to Acme Corp: contact@acme.com. Phone: +91 9876543210.
"""

def test_redact_pii_detects_all_categories_with_stable_placeholders():
    from app.intake.service import redact_pii
    redacted, mapping, summary = redact_pii(PII_TEXT)

    # Placeholders present
    assert "[GST_1]" in redacted
    assert "[PAN_1]" in redacted
    assert "[AADHAAR_1]" in redacted
    assert "[PHONE_1]" in redacted
    assert "[EMAIL_1]" in redacted
    assert "[IFSC_1]" in redacted
    assert "[BANK_ACC_1]" in redacted

    # Raw PII not present in redacted text
    assert "27ABCDE1234F1Z5" not in redacted
    assert "ABCDE1234F" not in redacted
    assert "2345 6789 0123" not in redacted
    assert "contact@acme.com" not in redacted
    assert "HDFC0001234" not in redacted
    assert "123456789012" not in redacted

    # Stable placeholder for repeated PAN
    assert mapping["[PAN_1]"] == "ABCDE1234F"
    assert redacted.count("[PAN_1]") == 2

    # Hashes in summary
    assert "hashes" in summary and "counts" in summary
    assert summary["counts"]["PAN"] == 1
    assert len(summary["hashes"]["PAN"]) == 1


def test_restore_pii_roundtrip():
    from app.intake.service import redact_pii, restore_pii_str
    redacted, mapping, _ = redact_pii(PII_TEXT)
    restored = restore_pii_str(redacted, mapping)
    assert restored == PII_TEXT


def test_intake_normalizes_with_pii_redaction_and_verbatim_check_passes(monkeypatch, fake):
    monkeypatch.setattr(settings, "intake_redact_pii", True)
    # Gemini receives redacted text and echoes verbatim text with placeholders
    canned_answer = {
        "is_contract": True,
        "parties": ["Acme Corp (PAN: [PAN_1])", "Rahul Sharma"],
        "execution_date": "2026-10-15",
        "effective_date": None,
        "jurisdiction": "India",
        "clauses": [
            {
                "clause_number": "1",
                "heading": "PAYMENT",
                "clause_type": "other",
                "text": "The client shall wire funds to Account: [BANK_ACC_1] at IFSC: [IFSC_1]."
            },
            {
                "clause_number": "2",
                "heading": "NOTICES",
                "clause_type": "other",
                "text": "Notices to Acme Corp: [EMAIL_1]. Phone: [PHONE_1]."
            }
        ]
    }
    f = fake(canned_answer)
    doc = normalize(PII_TEXT, "nda")

    # Sent prompt has redacted text, not raw PII
    prompt_sent = f.prompts[0]
    assert "[PAN_1]" in prompt_sent
    assert "contact@acme.com" not in prompt_sent
    assert "ABCDE1234F" not in prompt_sent

    # Normalized document has restored raw values
    assert doc.parties == ["Acme Corp (PAN: ABCDE1234F)", "Rahul Sharma"]
    assert len(doc.clauses) == 2
    assert "Account: 123456789012 at IFSC: HDFC0001234" in doc.clauses[0].text
    assert "contact@acme.com" in doc.clauses[1].text
    # And verbatim substring check passed against original text!
    assert all(c.text in doc.full_text for c in doc.clauses)


def test_intake_redaction_disabled_when_flag_off(monkeypatch, fake):
    monkeypatch.setattr(settings, "intake_redact_pii", False)
    canned_answer = {
        "is_contract": True,
        "parties": ["Acme Corp", "Rahul Sharma"],
        "execution_date": None,
        "effective_date": None,
        "jurisdiction": None,
        "clauses": [
            {
                "clause_number": "1",
                "heading": "PAYMENT",
                "clause_type": "other",
                "text": "The client shall wire funds to Account: 123456789012 at IFSC: HDFC0001234."
            }
        ]
    }
    f = fake(canned_answer)
    normalize(PII_TEXT, "nda")
    prompt_sent = f.prompts[0]
    # Raw values sent directly when flag is false
    assert "contact@acme.com" in prompt_sent
    assert "ABCDE1234F" in prompt_sent


def test_intake_logs_no_raw_pii(monkeypatch, fake, caplog):
    monkeypatch.setattr(settings, "intake_redact_pii", True)
    fake({
        "is_contract": True,
        "parties": ["Acme Corp", "Rahul Sharma"],
        "execution_date": None,
        "effective_date": None,
        "jurisdiction": None,
        "clauses": [
            {
                "clause_number": "1",
                "heading": "PAYMENT",
                "clause_type": "other",
                "text": "The client shall wire funds to Account: [BANK_ACC_1] at IFSC: [IFSC_1]."
            }
        ]
    })
    with caplog.at_level("INFO", logger="app.intake.service"):
        normalize(PII_TEXT, "nda")

    assert "intake: redacted PII counts=" in caplog.text
    # Raw values must NEVER appear in logs
    assert "contact@acme.com" not in caplog.text
    assert "ABCDE1234F" not in caplog.text
    assert "2345 6789 0123" not in caplog.text
    assert "9876543210" not in caplog.text
    assert "123456789012" not in caplog.text

