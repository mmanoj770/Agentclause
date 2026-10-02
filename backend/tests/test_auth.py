from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

# no "with": skips the DB pool, so these run without a database

def test_health():
    assert client.get("/health").status_code == 200

def test_no_token_is_401():
    assert client.get("/lawyer/ping").status_code == 401

def test_garbage_token_is_401():
    r = client.get("/lawyer/ping", headers={"Authorization": "Bearer not-a-token"})
    assert r.status_code == 401
