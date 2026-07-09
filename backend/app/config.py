"""Application settings, loaded from environment / .env."""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Deployment environment. Anything other than "dev" tightens startup
    # checks (see app.security): the app refuses to boot with the default JWT
    # secret outside dev (Phase 2.2).
    env: str = "dev"

    anthropic_api_key: str = ""
    # Overridable via ANTHROPIC_MODEL in .env so a model bump needs no code
    # change; the default is only a zero-config convenience for local dev.
    anthropic_model: str = "claude-sonnet-5"
    newsapi_key: str = ""
    # Massive.com (formerly Polygon.io) — preferred bulk price source for the
    # recommendations screen. Leave empty to use Yahoo Finance only.
    massive_api_key: str = ""
    massive_base_url: str = "https://api.massive.com"
    cors_origins: str = "http://localhost:5173"

    # Phase 1 — concurrency & stability.
    # Bounded run pool: at most run_max_workers runs execute agents at once;
    # up to run_max_queued more may wait. Requests past that get HTTP 429.
    run_max_workers: int = 4
    run_max_queued: int = 8
    # Finished (done/error) runs and their event history are evicted this many
    # minutes after they finish, so memory stays flat over a long soak.
    run_ttl_minutes: int = 30
    run_sweep_seconds: int = 300  # how often the eviction sweep runs
    # Outbound-call budgets. The Anthropic SDK retries transient errors itself.
    llm_timeout_seconds: float = 60.0
    llm_max_retries: int = 2

    # Phase 3 — persistence & auth. SQLite by default (zero setup); swap to
    # e.g. postgresql+psycopg://user:pass@host/dbname when needed.
    database_url: str = "sqlite:///./investment.db"
    jwt_secret: str = "dev-only-secret-change-me-via-dotenv-0123456789"  # ≥32 bytes; override in .env
    jwt_expire_minutes: int = 60 * 24 * 7  # 7 days
    # SEC fair-access policy requires a descriptive UA with a real contact
    # address. Placeholder by default (no PII in tracked source, Phase 2.3);
    # set SEC_USER_AGENT in .env or the EDGAR tool refuses to fetch.
    sec_user_agent: str = "AI-Investment-Research/0.2 (set SEC_USER_AGENT in .env)"

    # Phase 2 (security) — rate limiting & abuse guards.
    rate_limit_enabled: bool = True  # set false in tests
    rate_limit_research: str = "5/minute"       # anonymous-abuse fence on the LLM path
    rate_limit_login: str = "10/minute"
    rate_limit_signup: str = "5/minute"
    rate_limit_run_now: str = "5/minute"        # /summaries/run, /recommendations/run
    rate_limit_send_now: str = "3/minute"       # /digest/send-now (sends real email)
    # Global daily budget: process-wide cap on research runs started per UTC
    # day. Past this, POST /research returns 429 — the real protection against
    # someone draining the Anthropic/NewsAPI budget (rate limiting is just the
    # first fence). Set 0 to disable.
    daily_run_budget: int = 200
    # Login brute-force lockout: after this many failed logins for one email
    # within the window, that email's logins return 429 until the window rolls.
    login_max_failures: int = 10
    login_lockout_minutes: int = 15

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
