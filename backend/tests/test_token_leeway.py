"""Token verification: clock-skew leeway, and only asymmetric algorithms are accepted."""
import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import HTTPException

from app.auth import dependencies
from app.auth.dependencies import CLOCK_SKEW_LEEWAY_SECONDS

_PRIVATE = ec.generate_private_key(ec.SECP256R1())


@pytest.fixture(autouse=True)
def es256(monkeypatch):
    monkeypatch.setattr(dependencies._jwks, "get_signing_key_from_jwt",
                        lambda token: SimpleNamespace(key=_PRIVATE.public_key()))


def token(iat_offset=0, exp_offset=3600):
    now = int(time.time())
    return jwt.encode({"sub": "u", "aud": "authenticated", "iss": dependencies._ISSUER, "iat": now + iat_offset, "exp": now + exp_offset},
                      _PRIVATE, algorithm="ES256")


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


def test_an_hs256_token_is_refused_whatever_it_is_signed_with():
    now = int(time.time())
    forged = jwt.encode({"sub": "u", "aud": "authenticated", "exp": now + 3600},
                        "any-shared-secret-of-at-least-thirty-two-bytes", algorithm="HS256")
    with pytest.raises(HTTPException) as e:
        dependencies._decode(forged)
    assert e.value.status_code == 401
