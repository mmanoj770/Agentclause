"""File routes, with no database and no AWS.

The DB connection is an in-memory fake, the user comes from a dependency override, and S3 is
a real boto3 client (presigning is local, it needs no network) whose API calls are stubbed.
A Stubber with nothing queued fails any unexpected S3 call, so "no S3 call" is asserted too.
"""
import base64
import json
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import boto3
import pytest
from botocore.config import Config
from botocore.stub import Stubber
from fastapi.testclient import TestClient
from psycopg.errors import UniqueViolation

from app.auth.dependencies import CurrentUser, get_current_user
from app.config import settings
from app.db import get_conn
from app.main import app
from app.storage.s3 import get_s3

PDF = "application/pdf"
BUCKET = "test-bucket"
SECRET = "test-secret-key-do-not-leak"

ORG_A, ORG_B = str(uuid.uuid4()), str(uuid.uuid4())
DOC = str(uuid.uuid4())
OTHER_DOC = str(uuid.uuid4())
LAWYER = str(uuid.uuid4())


class Result:
    def __init__(self, rows):
        self.rows = rows

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


class FakeConn:
    """Answers just the queries the file routes and get_document make."""

    def __init__(self, assigned_lawyer=None):
        self.doc = {"id": uuid.UUID(DOC), "org_id": ORG_A, "assigned_lawyer_id": assigned_lawyer,
                    "state": "drafted"}
        self.versions = []  # {"version_no", "storage_key"}
        self.audit = []
        self.race_once = False  # another request takes the next number first

    def transaction(self):
        class _Tx:
            def __enter__(self_):
                return self_

            def __exit__(self_, *exc):
                return False

        return _Tx()

    def execute(self, sql, params=()):
        s = " ".join(sql.split())
        if s.startswith("select * from documents where id"):
            return Result([self.doc] if str(params[0]) == DOC else [])
        if "from document_versions where document_id = %s and storage_key" in s:
            return Result([v for v in self.versions if v["storage_key"] == params[1]])
        if "max(version_no)" in s:
            return Result([{"n": max((v["version_no"] for v in self.versions), default=0) + 1}])
        if s.startswith("insert into document_versions"):
            _, number, key = params
            if self.race_once:
                self.race_once = False
                self.versions.append({"version_no": number, "storage_key": "someone-else"})
            if any(v["version_no"] == number for v in self.versions):
                raise UniqueViolation("duplicate key value")
            self.versions.append({"version_no": number, "storage_key": key})
            return Result([{"version_no": number}])
        if "from document_versions" in s and "order by version_no desc" in s:
            wanted = params[1]
            rows = sorted(self.versions, key=lambda v: -v["version_no"])
            return Result([v for v in rows if wanted is None or v["version_no"] == wanted][:1])
        if s.startswith("insert into audit_logs"):
            self.audit.append(params)
            return Result([])
        raise AssertionError(f"unexpected SQL: {s}")


def make_s3():
    client = boto3.client(
        "s3", region_name="ap-south-1",
        endpoint_url="https://s3.ap-south-1.amazonaws.com",
        aws_access_key_id="AKIATESTTESTTESTTEST", aws_secret_access_key=SECRET,
        config=Config(signature_version="s3v4"),
    )
    return client, Stubber(client)


def user(role="startup_user", org=ORG_A, uid=None):
    return CurrentUser(id=uid or str(uuid.uuid4()), email=None, role=role,
                       org_id=None if role == "lawyer" else org)


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setattr(settings, "s3_bucket", BUCKET)
    s3, stubber = make_s3()
    stubber.activate()
    conn = FakeConn()
    state = {"user": user()}
    app.dependency_overrides[get_current_user] = lambda: state["user"]
    app.dependency_overrides[get_conn] = lambda: conn
    app.dependency_overrides[get_s3] = lambda: s3
    yield type("Env", (), {"client": TestClient(app), "conn": conn, "stubber": stubber,
                           "state": state})
    app.dependency_overrides.clear()
    stubber.deactivate()


def own_key(name="contract.pdf"):
    return f"orgs/{ORG_A}/documents/{DOC}/{uuid.uuid4()}-{name}"


def stub_head(env, key, size=1000, content_type=PDF):
    env.stubber.add_response(
        "head_object", {"ContentLength": size, "ContentType": content_type},
        {"Bucket": BUCKET, "Key": key})


def upload(env, doc=DOC, **over):
    body = {"filename": "My Contract.pdf", "content_type": PDF, "size": 1000, **over}
    return env.client.post(f"/documents/{doc}/files/upload-url", json=body)


def confirm(env, key, doc=DOC):
    return env.client.post(f"/documents/{doc}/files/confirm", json={"key": key})


# --- upload-url ---------------------------------------------------------------------------

def test_upload_url_good(env):
    r = upload(env)
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"key", "url", "fields"}
    assert body["key"].startswith(f"orgs/{ORG_A}/documents/{DOC}/")
    assert body["key"].endswith("-My_Contract.pdf")
    assert body["url"].startswith("https://")
    assert body["fields"]["Content-Type"] == PDF
    assert SECRET not in r.text


def test_upload_url_pins_type_and_size_in_the_policy(env):
    fields = upload(env).json()["fields"]
    policy = json.loads(base64.b64decode(fields["policy"]))
    assert {"Content-Type": PDF} in policy["conditions"]
    assert ["content-length-range", 1, 26214400] in policy["conditions"]


def test_upload_url_expires_after_ttl(env):
    policy = json.loads(base64.b64decode(upload(env).json()["fields"]["policy"]))
    expires = datetime.strptime(policy["expiration"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    left = expires - datetime.now(timezone.utc)
    assert timedelta(seconds=290) < left <= timedelta(seconds=300)


@pytest.mark.parametrize("over", [
    {"content_type": "text/plain"},
    {"content_type": "application/x-msdownload"},
    {"size": 26214401},
    {"size": 0},
    {"size": -5},
    {"filename": ""},
])
def test_upload_url_rejects_bad_input(env, over):
    assert upload(env, **over).status_code == 422


def test_upload_url_filename_cannot_escape_the_prefix(env):
    key = upload(env, filename="..\\..\\evil/../x.pdf").json()["key"]
    assert key.startswith(f"orgs/{ORG_A}/documents/{DOC}/")
    assert ".." not in key.split(f"{DOC}/", 1)[1]


# --- confirm ------------------------------------------------------------------------------

def test_confirm_good_creates_next_versions(env):
    for expected in (1, 2):
        key = own_key()
        stub_head(env, key)
        r = confirm(env, key)
        assert r.status_code == 200 and r.json() == {"version_no": expected}
    assert [v["version_no"] for v in env.conn.versions] == [1, 2]
    assert len(env.conn.audit) == 2
    env.stubber.assert_no_pending_responses()


def test_confirm_twice_is_one_version(env):
    key = own_key()
    stub_head(env, key)
    assert confirm(env, key).json() == {"version_no": 1}
    assert confirm(env, key).json() == {"version_no": 1}  # no second S3 call queued
    assert len(env.conn.versions) == 1


def test_confirm_retries_when_another_request_took_the_number(env):
    env.conn.race_once = True
    key = own_key()
    stub_head(env, key)
    r = confirm(env, key)
    assert r.status_code == 200 and r.json() == {"version_no": 2}
    assert {v["version_no"] for v in env.conn.versions} == {1, 2}


@pytest.mark.parametrize("key", [
    f"orgs/{ORG_A}/documents/{OTHER_DOC}/{uuid.uuid4()}-x.pdf",   # another document
    f"orgs/{ORG_B}/documents/{DOC}/{uuid.uuid4()}-x.pdf",         # another org
    f"orgs/{ORG_A}/documents/{DOC}/../{OTHER_DOC}/x.pdf",         # traversal
    f"orgs/{ORG_A}/documents/{DOC}/",                             # prefix only
    "x.pdf",
])
def test_confirm_rejects_a_key_from_elsewhere_without_asking_s3(env, key):
    assert confirm(env, key).status_code == 422
    assert env.conn.versions == []


def test_confirm_missing_object(env):
    key = own_key()
    env.stubber.add_client_error("head_object", service_error_code="404", http_status_code=404,
                                 expected_params={"Bucket": BUCKET, "Key": key})
    assert confirm(env, key).status_code == 422
    assert env.conn.versions == []


def test_confirm_oversize_object(env):
    key = own_key()
    stub_head(env, key, size=26214401)
    assert confirm(env, key).status_code == 422
    assert env.conn.versions == []


def test_confirm_wrong_type_object(env):
    key = own_key()
    stub_head(env, key, content_type="text/html")
    assert confirm(env, key).status_code == 422
    assert env.conn.versions == []


def test_confirm_s3_outage_is_502(env):
    key = own_key()
    env.stubber.add_client_error("head_object", service_error_code="500", http_status_code=500,
                                 expected_params={"Bucket": BUCKET, "Key": key})
    assert confirm(env, key).status_code == 502


# --- download-url -------------------------------------------------------------------------

def seed(env, n=2):
    for i in range(1, n + 1):
        env.conn.versions.append({"version_no": i, "storage_key": own_key(f"v{i}.pdf")})


def test_download_latest_and_specific_version(env):
    seed(env)
    latest = env.client.get(f"/documents/{DOC}/files/download-url").json()
    assert latest["version_no"] == 2 and latest["expires_in"] == 300
    first = env.client.get(f"/documents/{DOC}/files/download-url?version_no=1").json()
    assert first["version_no"] == 1
    assert SECRET not in json.dumps(first)


def test_download_url_expiry_and_filename(env):
    seed(env, 1)
    url = env.client.get(f"/documents/{DOC}/files/download-url").json()["url"]
    q = parse_qs(urlparse(url).query)
    assert q["X-Amz-Expires"] == ["300"]
    assert "attachment" in q["response-content-disposition"][0]
    assert 'filename="v1.pdf"' in q["response-content-disposition"][0]


def test_download_missing_version_is_404(env):
    seed(env, 1)
    assert env.client.get(f"/documents/{DOC}/files/download-url?version_no=9").status_code == 404
    env.conn.versions.clear()
    assert env.client.get(f"/documents/{DOC}/files/download-url").status_code == 404


def test_download_version_zero_is_422(env):
    assert env.client.get(f"/documents/{DOC}/files/download-url?version_no=0").status_code == 422


# --- document state -----------------------------------------------------------------------

@pytest.mark.parametrize("state", ["drafted", "revision_in_progress", "lawyer_commented"])
def test_upload_and_confirm_allowed_states(env, state):
    env.conn.doc["state"] = state
    assert upload(env).status_code == 200
    key = own_key()
    stub_head(env, key)
    assert confirm(env, key).status_code == 200


@pytest.mark.parametrize("state", ["under_ai_review", "pending_lawyer_review", "lawyer_approved",
                                   "delivered", "negotiation_in_progress"])
def test_upload_and_confirm_blocked_states_are_409(env, state):
    env.conn.doc["state"] = state
    assert upload(env).status_code == 409
    assert confirm(env, own_key()).status_code == 409  # no S3 call stubbed, none made
    assert env.conn.versions == []


def test_download_is_not_state_gated(env):
    seed(env, 1)
    env.conn.doc["state"] = "delivered"
    assert env.client.get(f"/documents/{DOC}/files/download-url").status_code == 200


# --- access control -----------------------------------------------------------------------

def test_other_org_gets_404_on_every_route(env):
    seed(env, 1)
    env.state["user"] = user(org=ORG_B)
    assert upload(env).status_code == 404
    assert confirm(env, own_key()).status_code == 404
    assert env.client.get(f"/documents/{DOC}/files/download-url").status_code == 404


def test_unknown_document_is_404(env):
    assert upload(env, doc=str(uuid.uuid4())).status_code == 404


def test_user_without_org_gets_404(env):
    env.state["user"] = user(org=None)
    assert upload(env).status_code == 404


def test_lawyer_cannot_upload_or_confirm(env):
    env.state["user"] = user("lawyer", uid=LAWYER)
    assert upload(env).status_code == 403
    assert confirm(env, own_key()).status_code == 403


def test_lawyer_download_needs_the_claim(env):
    seed(env, 1)
    env.state["user"] = user("lawyer", uid=LAWYER)
    assert env.client.get(f"/documents/{DOC}/files/download-url").status_code == 404  # unclaimed
    env.conn.doc["assigned_lawyer_id"] = LAWYER
    assert env.client.get(f"/documents/{DOC}/files/download-url").status_code == 200
    env.state["user"] = user("lawyer", uid=str(uuid.uuid4()))                        # someone else's
    assert env.client.get(f"/documents/{DOC}/files/download-url").status_code == 404


def test_storage_not_configured_is_503(monkeypatch):
    monkeypatch.setattr(settings, "s3_bucket", "")
    app.dependency_overrides[get_current_user] = lambda: user()
    app.dependency_overrides[get_conn] = lambda: FakeConn()
    try:
        r = TestClient(app).post(f"/documents/{DOC}/files/upload-url",
                                 json={"filename": "a.pdf", "content_type": PDF, "size": 1})
        assert r.status_code == 503
    finally:
        app.dependency_overrides.clear()
