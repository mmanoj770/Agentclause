import logging
from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]  # repo root, where .env.local lives
_LOCAL_MARKERS = ("localhost", "127.0.0.1", "[::1]")


def _is_local(value: str) -> bool:
    value = value.lower()
    return any(marker in value for marker in _LOCAL_MARKERS)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env.local", extra="ignore")

    # Deployment mode: "development" (the default) or "production". Production turns on the startup
    # check in check_startup(). Set APP_ENV=production on the server BEFORE deploying the code that
    # checks it: the check does nothing until the variable exists, and the variable does nothing on old code.
    app_env: str = "development"

    database_url: str = "postgresql://postgres:postgres@127.0.0.1:54322/postgres"
    supabase_url: str = "http://127.0.0.1:54321"
    # Comma-separated browser origins allowed by CORS (no "*"). Kept as a str because
    # pydantic-settings would parse a list[str] env var as JSON.
    cors_allowed_origins: str = "http://localhost:3000"

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.cors_allowed_origins.split(",") if o.strip()]

    # POST /intake/normalize limits per user. Each request can trigger up to 3 model calls, so lower these
    # if model costs matter. Counted in memory per process: exact only while the server runs a single worker
    # (see the systemd unit). Recheck before anyone adds workers or a second server.
    intake_rate_limit_per_minute: int = Field(default=5, ge=1)
    intake_rate_limit_per_hour: int = Field(default=30, ge=1)

    # Which contract types users may pick. Nothing is "live" yet, so include in_build while developing.
    selectable_contract_statuses: list[str] = ["live"]

    # Gemini (free tier) - used by the Drafting Agent.
    # Model names are config so a retired model can be swapped via .env.local
    # (GEMINI_EMBEDDING_MODEL=..., GEMINI_GENERATION_MODEL=...) without code changes.
    # text-embedding-004 was shut down by Google on 2026-01-14.
    # Changing the embedding model means re-embedding every clause (vectors from
    # different models are not comparable): set embedding = null, then re-run embed_runner.
    gemini_api_key: str = ""
    gemini_embedding_model: str = "gemini-embedding-001"
    gemini_generation_model: str = "gemini-3.5-flash-lite"
    # Intake normalisation (R2): extraction only, so the cheapest model that follows a JSON schema.
    gemini_intake_model: str = "gemini-3.5-flash-lite"
    intake_redact_pii: bool = True

    # File storage (S3). Credentials come from the standard AWS chain (env vars, profile,
    # role); the three aws_* fields below exist only so they can be set in .env.local.
    # India region for DPDP data residency.
    aws_region: str = "ap-south-1"
    s3_bucket: str = ""                       # empty = storage routes answer 503
    s3_endpoint_url: str | None = None        # default: the regional AWS endpoint
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    aws_session_token: str | None = None
    upload_url_ttl_seconds: int = 300
    download_url_ttl_seconds: int = 300
    max_upload_bytes: int = 26_214_400        # 25 MB
    allowed_upload_types: list[str] = [
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "image/png",
        "image/jpeg",
    ]

    def check_startup(self) -> None:
        """Log the mode; in production refuse to start if a setting still has its local-development value.

        Messages name settings only, never their values (a database URL can contain a password).
        s3_bucket and the model keys are deliberately not checked: empty means the feature answers a handled 503.
        """
        mode = self.app_env.strip().lower()
        if mode not in ("development", "production"):
            raise RuntimeError("APP_ENV must be 'development' or 'production'")
        logger.info("startup mode=%s", mode)
        if mode != "production":
            return
        problems = []
        if _is_local(self.database_url):
            problems.append("DATABASE_URL")
        if _is_local(self.supabase_url):
            problems.append("SUPABASE_URL")
        if not self.cors_origins or any(_is_local(o) for o in self.cors_origins):
            problems.append("CORS_ALLOWED_ORIGINS")
        if problems:
            raise RuntimeError("Refusing to start in production: these settings are missing or still "
                               "local-development values: " + ", ".join(problems))


settings = Settings()
