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

# Role-separation tests log in to the live project. Without the TEST_* variables they are skipped, so a
# plain `pytest` run is clean. A skip is not a pass: REQUIRE_ACCESS_TESTS=1 turns the skip into a failure,
# and the summary always prints how many tests were skipped this way.
ACCESS_SKIP_TAG = "[access-tests]"


def _access_creds(*names):
    needed = ("SUPABASE_URL", "SUPABASE_ANON_KEY", *names)
    missing = [n for n in needed if not os.environ.get(n)]
    if not missing:
        return tuple(os.environ[n] for n in names)
    msg = f"{ACCESS_SKIP_TAG} not set: {', '.join(missing)}"
    if os.environ.get("REQUIRE_ACCESS_TESTS") == "1":
        pytest.fail(f"{msg} (REQUIRE_ACCESS_TESTS=1, so this is a failure, not a skip)", pytrace=False)
    pytest.skip(msg)


_access_skips = []


def pytest_runtest_logreport(report):
    if report.skipped and ACCESS_SKIP_TAG in str(report.longrepr):
        _access_skips.append(report.nodeid)


def pytest_terminal_summary(terminalreporter):
    if _access_skips:
        terminalreporter.section("access tests")
        terminalreporter.write_line(
            f"ACCESS TESTS SKIPPED: {len(_access_skips)} (TEST_* variables missing). "
            "These are the role-separation tests; a skip is not a pass. "
            "Set the variables, or run with REQUIRE_ACCESS_TESTS=1 to make this a failure."
        )


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c

@pytest.fixture(scope="session")
def startup():
    return login(*_access_creds("TEST_STARTUP_EMAIL", "TEST_STARTUP_PASSWORD"))

@pytest.fixture(scope="session")
def startup_b():
    return login(*_access_creds("TEST_STARTUP_B_EMAIL", "TEST_STARTUP_B_PASSWORD"))

@pytest.fixture(scope="session")
def lawyer():
    return login(*_access_creds("TEST_LAWYER_EMAIL", "TEST_LAWYER_PASSWORD"))


def pytest_configure(config):
    config.addinivalue_line("markers", "live: calls a real external API; skipped unless explicitly enabled")
