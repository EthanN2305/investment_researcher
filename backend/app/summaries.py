"""Daily summary service — runs the agent pipeline headlessly and stores results.

Used by both the APScheduler daily job and the `POST /summaries/run` demo
endpoint. Unlike interactive runs (SSE + clarifying questions), scheduled runs
must never block on a human: depth/lens are pre-filled and any residual
planner interrupt (e.g. share-class ambiguity) is auto-answered with the
ticker exactly as the user saved it.
"""
from __future__ import annotations

import json
import logging
import re
import uuid

from langgraph.types import Command
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db_models import Holding, StoredReport, User, WatchlistItem
from app.graph import events
from app.models import FinalReport
from app.routers.portfolio import load_portfolio_context
from app.tools.base import PriceHistoryProvider

logger = logging.getLogger("summaries")

_MAX_INTERRUPT_RESUMES = 3
_SHORT_SUMMARY_SENTENCES = 3
_SHORT_SUMMARY_CHARS = 500

# The Technical Analysis Agent embeds the latest close in claim evidence,
# e.g. "close=359.91, sma50=342.10". Extracting it gives every stored
# summary a price snapshot the portfolio valuation can fall back to.
_CLOSE_RE = re.compile(r"\bclose=(\d+(?:\.\d+)?)")


def extract_price_from_report(report: FinalReport) -> float | None:
    """Latest close parsed from the report's claims (technicals first)."""
    ordered = sorted(report.agent_reports, key=lambda r: r.agent != "technicals")
    for agent_report in ordered:
        for claim in agent_report.claims:
            m = _CLOSE_RE.search(claim.evidence or "")
            if m:
                try:
                    return float(m.group(1))
                except ValueError:
                    continue
    return None


def tickers_for_user(db: Session, user: User) -> list[str]:
    """Distinct watchlist + portfolio tickers, alphabetical."""
    watch = db.scalars(
        select(WatchlistItem.ticker).where(WatchlistItem.user_id == user.id)
    ).all()
    held = db.scalars(
        select(Holding.ticker).where(Holding.user_id == user.id)
    ).all()
    return sorted({*watch, *held})


def short_summary(report: FinalReport) -> str:
    """A few sentences for the feed; the full report stays one click away."""
    text = (report.recommendation.summary or "").strip()
    if not text:
        n = sum(len(r.claims) for r in report.agent_reports)
        return f"{n} claims gathered across {len(report.agent_reports)} agents."
    sentences = re.split(r"(?<=[.!?])\s+", text)
    out = " ".join(sentences[:_SHORT_SUMMARY_SENTENCES])
    return out[:_SHORT_SUMMARY_CHARS]


def run_pipeline_headless(
    graph, ticker: str, portfolio_context: dict | None
) -> FinalReport | None:
    """Invoke the graph without a human in the loop.

    Interrupts are auto-resumed with the saved ticker (share-class questions
    resolve to exactly what the user watchlisted; anything else falls back to
    the planner's defaults).
    """
    run_id = f"sched-{uuid.uuid4().hex[:10]}"
    events.register(run_id)  # agents emit progress; nobody subscribes — fine
    config = {"configurable": {"thread_id": run_id}}
    payload: dict = {
        "run_id": run_id, "ticker": ticker,
        "depth": "deep", "lens": "balanced",
    }
    if portfolio_context:
        payload["portfolio_context"] = portfolio_context

    result = graph.invoke(payload, config)
    for _ in range(_MAX_INTERRUPT_RESUMES):
        if not (isinstance(result, dict) and result.get("__interrupt__")):
            break
        result = graph.invoke(Command(resume=ticker), config)
    return result.get("final_report") if isinstance(result, dict) else None


def latest_stored_report(
    db: Session, user: User, ticker: str
) -> FinalReport | None:
    row = db.scalar(
        select(StoredReport)
        .where(StoredReport.user_id == user.id, StoredReport.ticker == ticker)
        .order_by(StoredReport.created_at.desc(), StoredReport.id.desc())
        .limit(1)
    )
    if row is None:
        return None
    try:
        return FinalReport(**json.loads(row.report_json))
    except Exception:  # noqa: BLE001 — a corrupt old row shouldn't kill the job
        return None


def run_summary_for_ticker(
    db: Session,
    user: User,
    ticker: str,
    *,
    graph,
    prices: PriceHistoryProvider,
    trigger: str = "scheduled",
) -> StoredReport | None:
    """Run the pipeline for one (user, ticker), store the report, fire alerts."""
    previous = latest_stored_report(db, user, ticker)

    context = load_portfolio_context(db, user)
    portfolio_context = context.model_dump() if context.holdings else None

    try:
        report = run_pipeline_headless(graph, ticker, portfolio_context)
    except Exception as exc:  # noqa: BLE001 — one bad ticker mustn't stop the job
        logger.warning("summary run failed for %s/%s: %s", user.email, ticker, exc)
        return None
    if report is None:
        logger.warning("summary run for %s/%s produced no report", user.email, ticker)
        return None

    stored = StoredReport(
        user_id=user.id,
        ticker=report.ticker,
        stance=report.recommendation.stance,
        confidence=report.recommendation.confidence,
        summary=short_summary(report),
        report_json=report.model_dump_json(),
        trigger=trigger,
        price=extract_price_from_report(report),
    )
    db.add(stored)
    db.commit()

    # Alerts run against the fresh report, diffed with the previous one.
    from app.alerts_engine import process_alerts_for_report

    fired = process_alerts_for_report(
        db, user,
        ticker=report.ticker, report=report, previous_report=previous,
        prices=prices, report_id=stored.id,
    )
    logger.info(
        "stored %s summary for %s/%s (stance=%s, conf=%.2f, alerts=%d)",
        trigger, user.email, ticker, stored.stance, stored.confidence, fired,
    )
    return stored


def run_summaries_for_user(
    db: Session, user: User, *, graph, prices: PriceHistoryProvider,
    trigger: str = "scheduled",
) -> list[StoredReport]:
    stored = []
    for ticker in tickers_for_user(db, user):
        result = run_summary_for_ticker(
            db, user, ticker, graph=graph, prices=prices, trigger=trigger
        )
        if result is not None:
            stored.append(result)
    return stored
