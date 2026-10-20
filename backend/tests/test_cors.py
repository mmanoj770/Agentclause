from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

# no "with": skips the DB pool; the CORS middleware answers preflights before routing

URL = "/documents/00000000-0000-0000-0000-000000000000/files/upload-url"

def preflight(origin: str):
    return client.options(URL, headers={
        "Origin": origin,
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "authorization,content-type",
    })

def test_preflight_from_allowed_origin():
    r = preflight("http://localhost:3000")
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert "POST" in r.headers["access-control-allow-methods"]
    assert "access-control-allow-credentials" not in r.headers

def test_preflight_from_unlisted_origin():
    r = preflight("http://evil.example.com")
    assert r.status_code == 400
    assert "access-control-allow-origin" not in r.headers
