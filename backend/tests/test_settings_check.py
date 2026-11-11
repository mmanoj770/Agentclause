"""Startup check (APP_ENV). Settings are built with _env_file=None so a local .env.local
cannot change the result."""
import logging

import pytest

from app.config import Settings

REAL = dict(database_url="postgresql://app:s3cretpw@db.example.com:5432/app",
            supabase_url="https://abc.supabase.co",
            cors_allowed_origins="https://vidhata-pi.vercel.app")


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    """Real environment variables beat code defaults, so clear the ones these tests rely on."""
    for name in ("APP_ENV", "DATABASE_URL", "SUPABASE_URL", "CORS_ALLOWED_ORIGINS"):
        monkeypatch.delenv(name, raising=False)


def make(**kw):
    return Settings(_env_file=None, **kw)


def test_development_defaults_start_fine():
    make().check_startup()


def test_production_with_local_defaults_refuses_and_names_the_settings():
    with pytest.raises(RuntimeError) as e:
        make(app_env="production").check_startup()
    msg = str(e.value)
    assert "DATABASE_URL" in msg and "SUPABASE_URL" in msg and "CORS_ALLOWED_ORIGINS" in msg


def test_production_with_real_values_starts():
    make(app_env="production", **REAL).check_startup()


def test_production_flags_only_the_bad_setting():
    with pytest.raises(RuntimeError) as e:
        make(app_env="production", **{**REAL, "cors_allowed_origins": "http://localhost:3000"}).check_startup()
    assert "CORS_ALLOWED_ORIGINS" in str(e.value) and "DATABASE_URL" not in str(e.value)


def test_error_never_contains_setting_values():
    with pytest.raises(RuntimeError) as e:
        make(app_env="production", **{**REAL, "database_url": "postgresql://app:s3cretpw@localhost/app"}).check_startup()
    assert "s3cretpw" not in str(e.value)


def test_unknown_mode_refuses():
    with pytest.raises(RuntimeError):
        make(app_env="prod").check_startup()


def test_mode_is_logged_at_startup(caplog):
    with caplog.at_level(logging.INFO):
        make(app_env="production", **REAL).check_startup()
    assert "startup mode=production" in caplog.text
