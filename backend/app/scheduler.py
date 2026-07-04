"""Background scheduler — Phase 4's first scheduled job.

APScheduler runs inside the FastAPI process (no broker/worker infra):
one daily cron job that re-researches every user's watchlist + portfolio
tickers and stores the results, so the morning feed is ready without
anyone re-running agents live.

Disable in tests / one-off scripts with SCHEDULER_ENABLED=false.
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal
from app.db_models import User
from app.summaries import run_summaries_for_user
from app.tools.base import PriceHistoryProvider

logger = logging.getLogger("scheduler")


def run_daily_summaries(graph, prices: PriceHistoryProvider) -> int:
    """One full sweep: every user, every watched/held ticker. Returns count.

    After each user's reports are stored, their email digest goes out if
    today matches their chosen cadence (daily / weekly / monthly).
    """
    from app.digest import send_digest_if_due

    total = 0
    db = SessionLocal()
    try:
        users = db.scalars(select(User)).all()
        logger.info("daily summary sweep starting for %d user(s)", len(users))
        for user in users:
            stored = run_summaries_for_user(db, user, graph=graph, prices=prices)
            total += len(stored)
            send_digest_if_due(db, user)
    finally:
        db.close()
    logger.info("daily summary sweep done: %d report(s) stored", total)
    return total


def start_scheduler(graph, prices: PriceHistoryProvider) -> BackgroundScheduler | None:
    if not settings.scheduler_enabled:
        logger.info("scheduler disabled (SCHEDULER_ENABLED=false)")
        return None
    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(
        run_daily_summaries,
        CronTrigger(
            hour=settings.daily_summary_hour_utc,
            minute=settings.daily_summary_minute_utc,
        ),
        args=[graph, prices],
        id="daily_summaries",
        max_instances=1,          # a slow sweep must not overlap the next one
        coalesce=True,            # missed runs (laptop asleep) collapse to one
        misfire_grace_time=3600,
    )
    scheduler.start()
    logger.info(
        "daily summary job scheduled for %02d:%02d UTC",
        settings.daily_summary_hour_utc, settings.daily_summary_minute_utc,
    )
    return scheduler
