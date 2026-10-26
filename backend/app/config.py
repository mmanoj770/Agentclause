from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]  # repo root, where .env.local lives

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env.local", extra="ignore")

    database_url: str = "postgresql://postgres:postgres@127.0.0.1:54322/postgres"
    supabase_url: str = "http://127.0.0.1:54321"
    supabase_jwt_secret: str | None = None  # only needed for HS256 tokens
    # Comma-separated browser origins allowed by CORS (no "*"). Kept as a str because
    # pydantic-settings would parse a list[str] env var as JSON.
    cors_allowed_origins: str = "http://localhost:3000"

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.cors_allowed_origins.split(",") if o.strip()]

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

settings = Settings()
