"""ORM models — users, portfolio holdings, and stated preferences.

Deliberately simple (per the Phase 3 spec): one user → many holdings,
one user → one preferences row. Preferences store only what the user
explicitly tells us — no inferred/learned data (that's Phase 5).
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, String, UniqueConstraint
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
