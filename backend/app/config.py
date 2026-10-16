from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]  # repo root, where .env.local lives

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env.local", extra="ignore")

    database_url: str = "postgresql://postgres:postgres@127.0.0.1:54322/postgres"
    supabase_url: str = "http://127.0.0.1:54321"
    supabase_jwt_secret: str | None = None  # only needed for HS256 tokens
    frontend_origin: str = "http://localhost:3000"

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

settings = Settings()
