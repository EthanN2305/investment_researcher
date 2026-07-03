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
    # SEC fair-access policy requires a descriptive UA with contact info.
    sec_user_agent: str = "AI-Investment-Research/0.2 (ngoe5@uci.edu)"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
