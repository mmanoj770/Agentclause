"""Router-level tests for POST /intake/normalize: role, size cap, rate limit, usage log.

No credentials, no network, no model calls: the signed-in user is replaced and intake.service.normalize
is replaced by a fake. Complements test_intake_service.py, which covers the extraction itself."""
import logging

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.auth.dependencies import CurrentUser, get_current_user
from app.config import Settings, settings
from app.intake import service as intake_service
from app.intake.limits import MAX_CONTRACT_CHARS, SlidingWindowLimiter
from app.intake.service import IntakeNotConfiguredError, IntakeUnavailableError, NotAContractError
from app.main import app

URL = "/intake/normalize"
MARKER = "ZZ-CONTRACT-MARKER-ZZ"


def body(text="x"):
    return {"contract_text": text, "contract_type_id": "nda"}


class FakeNormalize:
    """Stands in for intake.service.normalize. Counts calls; raises the configured error."""

    def __init__(self, error=None):
        self.error = error or NotAContractError("The text does not appear to be a contract.")
        self.calls = 0

    def __call__(self, contract_text, contract_type_id="nda", **kwargs):
        self.calls += 1
        raise self.error


@pytest.fixture
def setup(monkeypatch):
    """setup(role, error, uid, org_id) installs the fake user and the fake service function."""
    def _setup(role="startup_user", error=None, uid="user-1", org_id="org-1"):
        fake = FakeNormalize(error)
        monkeypatch.setattr(intake_service, "normalize", fake)
        app.dependency_overrides[get_current_user] = lambda: CurrentUser(id=uid, email=None, role=role, org_id=org_id)
        return fake

    yield _setup
    app.dependency_overrides.pop(get_current_user, None)


client = TestClient(app)


def test_no_token_gets_401():
    assert client.post(URL, json=body()).status_code == 401


def test_lawyer_gets_403_and_service_not_called(setup):
    fake = setup(role="lawyer")
    assert client.post(URL, json=body()).status_code == 403
    assert fake.calls == 0


def test_startup_without_organization_is_400_and_uses_no_quota(setup):
    fake = setup(org_id=None)
    for _ in range(settings.intake_rate_limit_per_minute + 2):
        assert client.post(URL, json=body()).status_code == 400
    assert fake.calls == 0


def test_oversize_text_is_rejected_before_the_service(setup):
    fake = setup()
    r = client.post(URL, json=body("a" * (MAX_CONTRACT_CHARS + 1)))
    assert r.status_code == 422
    assert fake.calls == 0


def test_text_at_the_cap_reaches_the_service(setup):
    fake = setup()
    r = client.post(URL, json=body("a" * MAX_CONTRACT_CHARS))
    assert r.status_code == 422  # the fake says "not a contract": proves the service was reached
    assert fake.calls == 1


@pytest.mark.parametrize("error", [IntakeNotConfiguredError("not configured"),
                                   IntakeUnavailableError("busy")])
def test_not_configured_and_unavailable_stay_handled_503s(setup, error):
    setup(error=error)
    assert client.post(URL, json=body()).status_code == 503


def test_rate_limit_returns_429_without_calling_the_service(setup):
    fake = setup()
    allowed = settings.intake_rate_limit_per_minute
    responses = [client.post(URL, json=body()) for _ in range(allowed + 1)]
    assert [r.status_code for r in responses[:allowed]] == [422] * allowed
    assert responses[allowed].status_code == 429
    assert responses[allowed].headers["Retry-After"] == "60"
    assert fake.calls == allowed


def test_rate_limit_is_per_user(setup):
    setup(uid="user-1")
    for _ in range(settings.intake_rate_limit_per_minute + 1):
        client.post(URL, json=body())
    setup(uid="user-2")
    assert client.post(URL, json=body()).status_code == 422


def test_usage_log_has_ids_and_sizes_but_never_the_contract_text(setup, caplog):
    setup(uid="user-77")
    with caplog.at_level(logging.INFO):
        client.post(URL, json=body(MARKER * 3))
    assert MARKER not in caplog.text
    assert "user=user-77" in caplog.text
    assert f"chars={len(MARKER) * 3}" in caplog.text
    assert "outcome=not_a_contract" in caplog.text


def test_the_cap_comes_from_the_setting():
    assert MAX_CONTRACT_CHARS == settings.intake_max_contract_chars


def test_limiter_window_expires():
    now = [0.0]
    lim = SlidingWindowLimiter(limits=((60, 2),), clock=lambda: now[0])
    assert lim.allow("u") and lim.allow("u")
    assert not lim.allow("u")
    now[0] = 61.0
    assert lim.allow("u")


def test_rate_limit_settings_defaults_and_minimum(monkeypatch):
    monkeypatch.delenv("INTAKE_RATE_LIMIT_PER_MINUTE", raising=False)
    monkeypatch.delenv("INTAKE_RATE_LIMIT_PER_HOUR", raising=False)
    monkeypatch.delenv("INTAKE_MAX_CONTRACT_CHARS", raising=False)
    s = Settings(_env_file=None)
    assert (s.intake_rate_limit_per_minute, s.intake_rate_limit_per_hour) == (5, 30)
    assert s.intake_max_contract_chars == 500_000  # unchanged from before the setting existed
    with pytest.raises(ValidationError):
        Settings(_env_file=None, intake_rate_limit_per_minute=0)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, intake_max_contract_chars=0)
