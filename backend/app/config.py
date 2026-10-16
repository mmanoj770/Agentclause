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

    # D3: Gemini API key for clause embeddings (text-embedding-004, 768 dims)
    gemini_api_key: str = ""

settings = Settings()
