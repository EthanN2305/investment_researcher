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
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal
from app.db_models import User
from app.summaries import run_summaries_for_user
from app.tools.base import PriceHistoryProvider

logger = logging.getLogger("scheduler")


def run_daily_summaries(
    graph, prices: PriceHistoryProvider, market=None, llm=None
) -> int:
    """One full sweep: every user, every watched/held ticker. Returns count.

    After each user's reports are stored, their email digest goes out if
    today matches their chosen cadence (daily / weekly / monthly).

    Phase 3.3: a single `shared_cache` spans the whole sweep, so each distinct
    ticker's non-personalized report is computed once and reused across users
    (when `market` and `llm` are provided). Cost then scales with distinct
    tickers plus cheap per-user re-syntheses, not users × tickers.
    """
    from app.digest import send_digest_if_due

    total = 0
    shared_cache: dict = {}
    db = SessionLocal()
    try:
        users = db.scalars(select(User)).all()
        logger.info("daily summary sweep starting for %d user(s)", len(users))
        for user in users:
            stored = run_summaries_for_user(
                db, user, graph=graph, prices=prices,
                market=market, llm=llm, shared_cache=shared_cache,
            )
            total += len(stored)
            send_digest_if_due(db, user)
    finally:
        db.close()
    logger.info(
        "daily summary sweep done: %d report(s) across %d distinct ticker(s)",
        total, len(shared_cache),
    )
    return total


def start_scheduler(
    graph, prices: PriceHistoryProvider, run_manager=None, market=None, llm=None
) -> BackgroundScheduler | None:
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
        args=[graph, prices, market, llm],
        id="daily_summaries",
        max_instances=1,          # a slow sweep must not overlap the next one
        coalesce=True,            # missed runs (laptop asleep) collapse to one
        misfire_grace_time=3600,
    )
    # Phase 1.3: evict finished runs + their event history on a TTL, so memory
    # stays flat over a long soak. Runs in-process on the same scheduler rather
    # than a bespoke timer thread.
    if run_manager is not None:
        scheduler.add_job(
            run_manager.sweep,
            IntervalTrigger(seconds=settings.run_sweep_seconds),
            id="evict_finished_runs",
            max_instances=1,
            coalesce=True,
        )
    # Phase 4: resolve matured recommendation outcomes, then periodically re-fit
    # the confidence calibration from the resolved set.
    from app import calibration

    scheduler.add_job(
        calibration.backfill_outcomes,
        IntervalTrigger(hours=settings.calibration_backfill_hours),
        args=[prices],
        id="calibration_backfill",
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        calibration.refit,
        IntervalTrigger(hours=settings.calibration_refit_hours),
        id="calibration_refit",
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    logger.info(
        "daily summary job scheduled for %02d:%02d UTC",
        settings.daily_summary_hour_utc, settings.daily_summary_minute_utc,
    )
    return scheduler
