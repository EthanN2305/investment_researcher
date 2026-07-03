"""Application settings, loaded from environment / .env."""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-5"
    newsapi_key: str = ""
    cors_origins: str = "http://localhost:5173"
    # Phase 3 — persistence & auth. SQLite by default (zero setup); swap to
    # e.g. postgresql+psycopg://user:pass@host/dbname when needed.
    database_url: str = "sqlite:///./investment.db"
    jwt_secret: str = "dev-only-secret-change-me-via-dotenv-0123456789"  # ≥32 bytes; override in .env
    jwt_expire_minutes: int = 60 * 24 * 7  # 7 days
    # SEC fair-access policy requires a descriptive UA with contact info.
    sec_user_agent: str = "AI-Investment-Research/0.2 (ngoe5@uci.edu)"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
