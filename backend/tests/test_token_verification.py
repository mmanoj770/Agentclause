"""Token verification rules: pinned algorithms, algorithm confusion, JWKS behaviour, required claims, generic errors."""
import base64
import hashlib
import hmac
import json
import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from fastapi import HTTPException
from jwt import PyJWKClient
from jwt.algorithms import ECAlgorithm
from jwt.exceptions import PyJWKClientError

from app.auth import dependencies

_PRIVATE = ec.generate_private_key(ec.SECP256R1())
_PUBLIC = _PRIVATE.public_key()
GENERIC = "Invalid or missing token"


def _claims(**over):
    now = int(time.time())
    base = {"sub": "u", "aud": "authenticated", "iss": dependencies._ISSUER, "iat": now, "exp": now + 3600}
    base.update(over)
    return {k: v for k, v in base.items() if v is not None}


def _es256(key=_PRIVATE, **over):
    return jwt.encode(_claims(**over), key, algorithm="ES256", headers={"kid": "k1"})


def _b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=")


def _refused(token):
    with pytest.raises(HTTPException) as e:
        dependencies._decode(token)
    assert e.value.status_code == 401
    assert e.value.detail == GENERIC  # no reason is given, whatever the cause
    return e.value


@pytest.fixture
def good_key(monkeypatch):
    monkeypatch.setattr(dependencies._jwks, "get_signing_key_from_jwt",
                        lambda token: SimpleNamespace(key=_PUBLIC))


def test_the_accepted_algorithms_are_pinned():
    assert dependencies.ALLOWED_ALGORITHMS == ("ES256", "RS256")


def test_a_valid_es256_token_is_accepted(good_key):
    assert dependencies._decode(_es256())["sub"] == "u"


def test_alg_none_is_refused(good_key):
    header = _b64(json.dumps({"alg": "none", "typ": "JWT"}).encode())
    payload = _b64(json.dumps(_claims()).encode())
    _refused((header + b"." + payload + b".").decode())


def test_hs256_signed_with_any_secret_is_refused(good_key):
    forged = jwt.encode(_claims(), "any-shared-secret-of-at-least-thirty-two-bytes", algorithm="HS256")
    _refused(forged)


def test_algorithm_confusion_hs256_signed_with_the_public_key_is_refused(good_key):
    pem = _PUBLIC.public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = _b64(json.dumps(_claims()).encode())
    sig = _b64(hmac.new(pem, header + b"." + payload, hashlib.sha256).digest())
    _refused((header + b"." + payload + b"." + sig).decode())


def test_a_token_signed_by_a_different_key_is_refused(good_key):
    _refused(_es256(key=ec.generate_private_key(ec.SECP256R1())))


def test_an_expired_token_is_refused(good_key):
    now = int(time.time())
    _refused(_es256(iat=now - 7200, exp=now - 3600))


def test_a_token_without_exp_is_refused(good_key):
    _refused(_es256(exp=None))


def test_the_wrong_audience_is_refused(good_key):
    _refused(_es256(aud="somebody-else"))


def test_the_wrong_issuer_is_refused(good_key):
    _refused(_es256(iss="https://evil.example/auth/v1"))


def test_a_token_without_an_issuer_is_refused(good_key):
    _refused(_es256(iss=None))


def test_an_unknown_kid_refreshes_the_jwks_once_then_rejects(monkeypatch):
    other = json.loads(ECAlgorithm.to_jwk(ec.generate_private_key(ec.SECP256R1()).public_key()))
    other["kid"] = "other"
    calls = []

    def fetch():
        calls.append(1)
        return {"keys": [other]}

    client = PyJWKClient("https://example.invalid/jwks")
    monkeypatch.setattr(client, "fetch_data", fetch)
    monkeypatch.setattr(dependencies, "_jwks", client)
    _refused(_es256())
    assert len(calls) == 2  # the first load, plus exactly one refresh


def test_a_jwks_fetch_failure_fails_closed_and_says_nothing_about_why(monkeypatch):
    def boom():
        raise PyJWKClientError("connection refused to internal-host:5432")

    client = PyJWKClient("https://example.invalid/jwks")
    monkeypatch.setattr(client, "fetch_data", boom)
    monkeypatch.setattr(dependencies, "_jwks", client)
    err = _refused(_es256())
    assert "internal-host" not in str(err.detail)
