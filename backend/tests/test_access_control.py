import pytest

ID = "00000000-0000-0000-0000-000000000000"

ALL_ROUTES = [
    ("POST", "/documents"), ("GET", "/documents"), ("GET", f"/documents/{ID}"),
    ("POST", f"/documents/{ID}/transition"),
    ("GET", "/queue"), ("POST", f"/queue/{ID}/claim"), ("POST", f"/queue/{ID}/release"),
    ("POST", f"/queue/{ID}/declare-conflict"),
    ("GET", "/me"), ("GET", "/lawyer/ping"),
]
LAWYER_ONLY = [r for r in ALL_ROUTES if r[1].startswith("/queue") or r[1] == "/lawyer/ping"]

@pytest.mark.parametrize("method,path", ALL_ROUTES)
def test_no_token_is_401(client, method, path):
    assert client.request(method, path, json={}).status_code == 401

@pytest.mark.parametrize("method,path", ALL_ROUTES)
def test_garbage_token_is_401(client, method, path):
    r = client.request(method, path, json={}, headers={"Authorization": "Bearer not.a.jwt"})
    assert r.status_code == 401

@pytest.mark.parametrize("method,path", LAWYER_ONLY)
def test_startup_user_blocked_from_lawyer_routes(client, startup, method, path):
    assert client.request(method, path, json={}, headers=startup).status_code == 403

def test_lawyer_cannot_create_documents(client, lawyer):
    assert client.post("/documents", json={}, headers=lawyer).status_code == 403

def test_lawyer_ping_allows_lawyer(client, lawyer):
    assert client.get("/lawyer/ping", headers=lawyer).status_code == 200