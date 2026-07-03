"""Database setup — SQLAlchemy 2.0 + SQLite.

SQLite keeps Phase 3 zero-install; the ORM models are Postgres-compatible,
so moving later is a one-line DATABASE_URL change (plus a real migration
tool if the schema starts evolving).
"""
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


# check_same_thread=False: FastAPI handles each request in a threadpool
# thread; sessions are still short-lived and per-request (see get_db).
engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False}
    if settings.database_url.startswith("sqlite")
    else {},
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db() -> None:
    """Create tables that don't exist yet. Idempotent; called at startup."""
    from app import db_models  # noqa: F401 — register models with Base

    Base.metadata.create_all(engine)


def get_db():
    """FastAPI dependency: one session per request, always closed."""
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()
