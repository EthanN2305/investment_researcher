"""ORM models — users, portfolio holdings, stated preferences (Phase 3),
plus watchlists, stored reports, alert rules, and notifications (Phase 4).

Preferences store only what the user explicitly tells us — no
inferred/learned data (that's Phase 5).
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    holdings: Mapped[list["Holding"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    preferences: Mapped["Preferences | None"] = relationship(
        back_populates="user", cascade="all, delete-orphan", uselist=False
    )


class Holding(Base):
    """One position: ticker, quantity, per-share cost basis.

    `sector` is captured best-effort at insert time (one market-data call)
    so the Portfolio Manager Agent can do sector-overlap math without N
    live lookups per research run.
    """

    __tablename__ = "holdings"
    __table_args__ = (UniqueConstraint("user_id", "ticker", name="uq_user_ticker"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    ticker: Mapped[str] = mapped_column(String(12))
    quantity: Mapped[float] = mapped_column(Float)
    cost_basis: Mapped[float] = mapped_column(Float)  # per share
    sector: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow
    )

    user: Mapped[User] = relationship(back_populates="holdings")


class Preferences(Base):
    """Explicitly stated preferences only (Phase 3 scope)."""

    __tablename__ = "preferences"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True
    )
    risk_tolerance: Mapped[str | None] = mapped_column(String(16))  # low|medium|high
    sector_interests: Mapped[str | None] = mapped_column(String(512))  # CSV
    growth_value_lean: Mapped[str | None] = mapped_column(String(16))  # growth|value|balanced
    time_horizon: Mapped[str | None] = mapped_column(String(16))  # short|medium|long
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow
    )

    user: Mapped[User] = relationship(back_populates="preferences")


# --- Phase 4: watchlists, stored reports, alerts, notifications ---------------


class WatchlistItem(Base):
    """A ticker the user tracks but doesn't necessarily own."""

    __tablename__ = "watchlist_items"
    __table_args__ = (
        UniqueConstraint("user_id", "ticker", name="uq_watchlist_user_ticker"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    ticker: Mapped[str] = mapped_column(String(12))
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class StoredReport(Base):
    """A persisted pipeline result (daily scheduled run or manual 'run now').

    The full FinalReport is stored as JSON so it can be re-opened later without
    re-running agents; the short columns exist so the feed can render without
    parsing the blob.
    """

    __tablename__ = "stored_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    ticker: Mapped[str] = mapped_column(String(12), index=True)
    stance: Mapped[str] = mapped_column(String(16), default="neutral")
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    summary: Mapped[str] = mapped_column(String(600), default="")  # short blurb
    report_json: Mapped[str] = mapped_column(Text)  # full FinalReport dump
    trigger: Mapped[str] = mapped_column(String(16), default="scheduled")  # scheduled|manual
    # Latest close extracted from the report's technical claims — lets the
    # portfolio valuation fall back to summary prices when live quotes fail.
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)


class RecommendationItem(Base):
    """One ranked pick from a recommendations sweep (global, not per-user).

    A sweep screens the S&P 500 + Nasdaq-100 universe on technicals, runs
    the agent pipeline on the survivors, and stores the top N here under a
    shared run_id. The latest run_id is what the Recommendations tab shows.
    """

    __tablename__ = "recommendation_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[str] = mapped_column(String(36), index=True)
    rank: Mapped[int] = mapped_column(Integer)
    ticker: Mapped[str] = mapped_column(String(12), index=True)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    screen_score: Mapped[float] = mapped_column(Float, default=0.0)
    momentum_3mo: Mapped[float | None] = mapped_column(Float, nullable=True)
    stance: Mapped[str] = mapped_column(String(16), default="neutral")
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    summary: Mapped[str] = mapped_column(String(600), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)


class AlertRule(Base):
    """One user-configured alert condition for one ticker."""

    __tablename__ = "alert_rules"
    __table_args__ = (
        UniqueConstraint("user_id", "ticker", "condition", name="uq_alert_rule"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    ticker: Mapped[str] = mapped_column(String(12))
    condition: Mapped[str] = mapped_column(String(32))  # see ALERT_CONDITIONS
    threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    email: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class EmailDigestPreference(Base):
    """How often (if at all) a user wants their daily feed emailed to them.

    One row per user. `weekday` only applies to weekly frequency
    (0 = Monday … 6 = Sunday, matching Python's datetime.weekday()).
    `last_sent_at` prevents duplicate sends if a sweep runs twice in a day.
    """

    __tablename__ = "email_digest_preferences"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    frequency: Mapped[str] = mapped_column(String(16), default="daily")  # daily|weekly|monthly
    weekday: Mapped[int | None] = mapped_column(nullable=True)  # weekly only, 0=Mon
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow
    )


class ReportOutcome(Base):
    """Phase 4: realized outcome of a stored recommendation, for calibration.

    Created pending when a report is stored, then resolved by a scheduled
    backfill job once the horizon has elapsed: it compares the ticker's total
    return to a benchmark (SPY) over H trading days and labels the stance
    correct/incorrect. `features_json` snapshots the derivation inputs
    (`prior_confidence`, coverage, disagreement, llm self-estimate) at
    prediction time so the fit never leaks future info.
    """

    __tablename__ = "report_outcomes"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Nullable so an outcome survives eviction of its source row; unique so we
    # never create two outcomes for the same stored report.
    stored_report_id: Mapped[int | None] = mapped_column(
        ForeignKey("stored_reports.id", ondelete="SET NULL"),
        nullable=True, unique=True, index=True,
    )
    ticker: Mapped[str] = mapped_column(String(12), index=True)
    stance: Mapped[str] = mapped_column(String(16))
    predicted_confidence: Mapped[float] = mapped_column(Float)  # as shown to the user
    prior_confidence: Mapped[float] = mapped_column(Float, default=0.5)  # pre-calibration
    features_json: Mapped[str] = mapped_column(Text, default="{}")
    prediction_date: Mapped[datetime] = mapped_column(DateTime, index=True)
    horizon_days: Mapped[int] = mapped_column(Integer, default=30)  # trading days
    benchmark: Mapped[str] = mapped_column(String(12), default="SPY")
    band_pct: Mapped[float] = mapped_column(Float, default=2.0)  # excess-return band
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    # Filled at resolution:
    ticker_return: Mapped[float | None] = mapped_column(Float, nullable=True)
    benchmark_return: Mapped[float | None] = mapped_column(Float, nullable=True)
    excess_return: Mapped[float | None] = mapped_column(Float, nullable=True)
    correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class CalibrationFit(Base):
    """Phase 4: a versioned confidence calibration fitted from resolved outcomes.

    Only one row is `active` at a time. `params_json` holds the fitted
    coefficients (Platt scaling by default); `brier` is the score on the
    training set. The active fit is loaded process-wide and applied inside
    `derive_confidence`; with none present the pipeline cold-starts on the
    hand-tuned defaults.
    """

    __tablename__ = "calibration_fits"

    id: Mapped[int] = mapped_column(primary_key=True)
    method: Mapped[str] = mapped_column(String(24), default="platt")
    params_json: Mapped[str] = mapped_column(Text, default="{}")
    n_samples: Mapped[int] = mapped_column(Integer, default=0)
    brier: Mapped[float | None] = mapped_column(Float, nullable=True)
    through_date: Mapped[str | None] = mapped_column(String(32), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)


class Notification(Base):
    """In-app notification produced when an alert rule fires."""

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    ticker: Mapped[str] = mapped_column(String(12))
    condition: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(String(1000), default="")
    report_id: Mapped[int | None] = mapped_column(
        ForeignKey("stored_reports.id", ondelete="SET NULL"), nullable=True
    )
    read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)
