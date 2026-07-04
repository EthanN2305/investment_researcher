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

    # Phase 4 — background jobs & alert email.
    scheduler_enabled: bool = True  # set false in tests/scripts
    daily_summary_hour_utc: int = 13   # 13:30 UTC ≈ just after US market open
    daily_summary_minute_utc: int = 30
    # SMTP is optional; without SMTP_HOST, alert emails log to the console.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_starttls: bool = True

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
