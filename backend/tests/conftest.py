from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env.test")

import os
import httpx
import pytest
from fastapi.testclient import TestClient
from app.main import app

def login(email, password):
    r = httpx.post(
        f"{os.environ['SUPABASE_URL']}/auth/v1/token?grant_type=password",
        headers={"apikey": os.environ["SUPABASE_ANON_KEY"]},
        json={"email": email, "password": password},
    )
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}

@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c

@pytest.fixture(scope="session")
def startup():
    return login(os.environ["TEST_STARTUP_EMAIL"], os.environ["TEST_STARTUP_PASSWORD"])

@pytest.fixture(scope="session")
def startup_b():
    if "TEST_STARTUP_B_EMAIL" not in os.environ or "TEST_STARTUP_B_PASSWORD" not in os.environ:
        pytest.skip("TEST_STARTUP_B_EMAIL or TEST_STARTUP_B_PASSWORD not set")
    return login(os.environ["TEST_STARTUP_B_EMAIL"], os.environ["TEST_STARTUP_B_PASSWORD"])

@pytest.fixture(scope="session")
def lawyer():
    return login(os.environ["TEST_LAWYER_EMAIL"], os.environ["TEST_LAWYER_PASSWORD"])