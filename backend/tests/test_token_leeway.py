"""Token clock-skew leeway: a freshly issued token must not be rejected because the server clock lags."""
import time

import jwt
import pytest
from fastapi import HTTPException

from app.auth import dependencies
from app.auth.dependencies import CLOCK_SKEW_LEEWAY_SECONDS

SECRET = "test-secret-with-at-least-thirty-two-bytes!"


@pytest.fixture(autouse=True)
def hs256(monkeypatch):
    monkeypatch.setattr(dependencies.settings, "supabase_jwt_secret", SECRET)


def token(iat_offset=0, exp_offset=3600):
    now = int(time.time())
    return jwt.encode({"sub": "u", "aud": "authenticated", "iat": now + iat_offset, "exp": now + exp_offset},
                      SECRET, algorithm="HS256")


def test_a_token_issued_a_second_in_the_future_is_accepted():
    assert dependencies._decode(token(iat_offset=1))["sub"] == "u"


def test_a_token_issued_well_in_the_future_is_still_refused():
    with pytest.raises(HTTPException) as e:
        dependencies._decode(token(iat_offset=CLOCK_SKEW_LEEWAY_SECONDS + 60))
    assert e.value.status_code == 401


def test_a_token_that_expired_long_ago_is_refused():
    with pytest.raises(HTTPException) as e:
        dependencies._decode(token(iat_offset=-7200, exp_offset=-3600))
    assert e.value.status_code == 401


def test_the_leeway_is_small():
    assert CLOCK_SKEW_LEEWAY_SECONDS <= 30
