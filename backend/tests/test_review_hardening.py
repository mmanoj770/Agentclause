"""Size cap on s3.read_object, and POST /reviews limited to startup users. No database, no AWS."""
import io

import boto3
import pytest
from botocore.config import Config
from botocore.response import StreamingBody
from botocore.stub import Stubber
from fastapi.testclient import TestClient

from app.auth.dependencies import CurrentUser, get_current_user
from app.config import settings
from app.main import app
from app.storage import s3 as storage

BUCKET = "test-bucket"
KEY = "org/doc/file.pdf"


def _client_with_object(data: bytes):
    # Fake values for the botocore Stubber; not real AWS keys.
    client = boto3.client("s3", region_name="ap-south-1", aws_access_key_id="test", aws_secret_access_key="test",
                          config=Config(signature_version="s3v4"))
    stub = Stubber(client)
    stub.add_response("get_object", {"Body": StreamingBody(io.BytesIO(data), len(data))},
                      {"Bucket": BUCKET, "Key": KEY})
    stub.activate()
    return client, stub


@pytest.fixture(autouse=True)
def _bucket(monkeypatch):
    monkeypatch.setattr(settings, "s3_bucket", BUCKET)


def test_read_object_returns_a_file_at_the_cap():
    client, stub = _client_with_object(b"x" * 10)
    assert storage.read_object(client, KEY, max_bytes=10) == b"x" * 10
    stub.assert_no_pending_responses()


def test_read_object_refuses_a_file_over_the_cap():
    client, _ = _client_with_object(b"x" * 11)
    with pytest.raises(storage.ObjectTooLargeError):
        storage.read_object(client, KEY, max_bytes=10)


def test_read_object_defaults_to_the_upload_cap(monkeypatch):
    monkeypatch.setattr(settings, "max_upload_bytes", 5)
    client, _ = _client_with_object(b"x" * 6)
    with pytest.raises(storage.ObjectTooLargeError):
        storage.read_object(client, KEY)


def test_read_object_error_does_not_name_the_key():
    client, _ = _client_with_object(b"x" * 11)
    with pytest.raises(storage.ObjectTooLargeError) as exc:
        storage.read_object(client, KEY, max_bytes=10)
    assert KEY not in str(exc.value)


@pytest.mark.parametrize("role,expected", [("lawyer", 403), ("system", 403)])
def test_post_reviews_is_for_startup_users_only(role, expected):
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(id="u", email=None, role=role, org_id=None)
    try:
        r = TestClient(app).post("/reviews", json={"contract_text": "An NDA.", "contract_type_id": "nda"})
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == expected
