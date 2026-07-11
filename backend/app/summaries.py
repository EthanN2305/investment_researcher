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
from datetime import datetime, timezone

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

# Fallback only (Phase 3.1): older stored reports predate structured metrics,
# so we can still recover the close by regexing the technicals agent's evidence
# string, e.g. "close=359.91, sma50=342.10".
_CLOSE_RE = re.compile(r"\bclose=(\d+(?:\.\d+)?)")


def extract_price_from_report(report: FinalReport) -> float | None:
    """Latest close for the report, technicals first.

    Phase 3.1: reads the structured `metrics["latest_close"]` the Technical
    Analysis Agent now emits — no parsing of our own generated prose. Falls
    back to regexing evidence strings only for reports stored before metrics
    existed.
    """
    ordered = sorted(report.agent_reports, key=lambda r: r.agent != "technicals")
    # 1) Structured metric (current reports).
    for agent_report in ordered:
        close = agent_report.metrics.get("latest_close")
        if close is not None:
            return float(close)
    # 2) Regex fallback (legacy reports without metrics).
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


def tickers_summarized_today(db: Session, user: User) -> set[str]:
    """Tickers that already have a stored report since UTC midnight.

    Used by run-now's "missing" mode so a second click (or a click after
    adding one holding) only spends agent/LLM tokens on tickers that don't
    yet have a fresh summary — instead of re-running the whole list.
    """
    since = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return set(
        db.scalars(
            select(StoredReport.ticker)
            .where(
                StoredReport.user_id == user.id,
                StoredReport.created_at >= since,
            )
            .distinct()
        ).all()
    )


def tickers_missing_today(db: Session, user: User) -> list[str]:
    """Watched/held tickers with no summary yet today, alphabetical."""
    have = tickers_summarized_today(db, user)
    return [t for t in tickers_for_user(db, user) if t not in have]


def short_summary(report: FinalReport) -> str:
    """A few sentences for the feed; the full report stays one click away."""
    text = (report.recommendation.summary or "").strip()
    if not text:
        n = sum(len(r.claims) for r in report.agent_reports)
        return f"{n} claims gathered across {len(report.agent_reports)} agents."
    sentences = re.split(r"(?<=[.!?])\s+", text)
    out = ""
    for sentence in sentences[:_SHORT_SUMMARY_SENTENCES]:
        candidate = f"{out} {sentence}" if out else sentence
        if len(candidate) > _SHORT_SUMMARY_CHARS:
            break
        out = candidate
    if out:
        return out
    # Even the first sentence overflows: cut at a word boundary instead.
    head = text[:_SHORT_SUMMARY_CHARS - 1].rsplit(" ", 1)[0]
    return head.rstrip(" ,;:—-") + "…"


def run_pipeline_headless(
    graph,
    ticker: str,
    portfolio_context: dict | None,
    *,
    depth: str = "deep",
    lens: str = "balanced",
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
        "depth": depth, "lens": lens,
    }
    if portfolio_context:
        payload["portfolio_context"] = portfolio_context

    try:
        result = graph.invoke(payload, config)
        for _ in range(_MAX_INTERRUPT_RESUMES):
            if not (isinstance(result, dict) and result.get("__interrupt__")):
                break
            result = graph.invoke(Command(resume=ticker), config)
        return result.get("final_report") if isinstance(result, dict) else None
    finally:
        # No SSE subscriber for headless runs, so free the history immediately
        # rather than leaking it for the process lifetime (Phase 1.3).
        events.unregister(run_id)


def shared_report_for_ticker(graph, ticker: str, cache: dict) -> FinalReport | None:
    """The non-personalized report for a ticker, computed once per sweep.

    Phase 3.3: the expensive part of a run (news LLM extraction, EDGAR/price
    fetches, technicals, comps, valuation) does not depend on the user, so the
    daily sweep computes it once per distinct ticker and caches it. Only the
    per-user portfolio fit + synthesis is redone per user (see
    `personalize_report`). Failures are cached as None so a broken ticker isn't
    retried for every user.
    """
    if ticker in cache:
        return cache[ticker]
    try:
        report = run_pipeline_headless(graph, ticker, portfolio_context=None)
    except Exception as exc:  # noqa: BLE001 — one bad ticker mustn't stop the sweep
        logger.warning("shared summary run failed for %s: %s", ticker, exc)
        report = None
    cache[ticker] = report
    return report


def personalize_report(
    shared: FinalReport,
    ticker: str,
    portfolio_context: dict,
    *,
    market,
    llm,
    lens: str | None = None,
) -> FinalReport:
    """Layer per-user personalization onto a shared report (Phase 3.3).

    Reuses every shared claim, runs only the (deterministic, no-LLM) Portfolio
    Manager Agent for this user, and re-synthesizes with one Recommendation
    LLM call over the combined claims. So the sweep's LLM cost is
    O(tickers) shared + O(users × their tickers) cheap re-syntheses, instead of
    a full pipeline per (user, ticker).
    """
    # Local imports avoid a circular import at module load (agents → tools).
    from app.agents import PortfolioManagerAgent, RecommendationAgent
    from app.models import AgentReport, PortfolioContext

    context = PortfolioContext(**portfolio_context)
    try:
        port_report = PortfolioManagerAgent(market).run(ticker, context)
    except Exception as exc:  # noqa: BLE001 — degrade to a flag, never crash
        logger.warning("portfolio agent failed for %s: %s", ticker, exc)
        port_report = AgentReport(
            agent="portfolio", status="failed", flags=["portfolio_unavailable"]
        )

    base = [r for r in shared.agent_reports if r.agent != "portfolio"]
    combined = base + [port_report]
    lens = lens or shared.lens
    flags = sorted({*shared.flags, *port_report.flags})
    rec, rec_flags = RecommendationAgent(llm).run(ticker, combined, lens, flags)
    return FinalReport(
        ticker=ticker,
        depth=shared.depth,
        lens=lens,
        agent_reports=combined,
        recommendation=rec,
        flags=sorted({*flags, *rec_flags}),
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


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
    market=None,
    llm=None,
    shared_cache: dict | None = None,
) -> StoredReport | None:
    """Run the pipeline for one (user, ticker), store the report, fire alerts.

    Phase 3.3: when `market`, `llm`, and `shared_cache` are supplied (the daily
    sweep), the ticker's non-personalized report is computed once and reused;
    users with holdings get a cheap personalized re-synthesis on top. Without
    them, falls back to a full per-(user, ticker) pipeline run.
    """
    previous = latest_stored_report(db, user, ticker)

    context = load_portfolio_context(db, user)
    personalize = bool(context.holdings)

    try:
        if shared_cache is not None and market is not None and llm is not None:
            shared = shared_report_for_ticker(graph, ticker, shared_cache)
            if shared is None:
                report = None
            elif personalize:
                report = personalize_report(
                    shared, ticker, context.model_dump(), market=market, llm=llm
                )
            else:
                report = shared
        else:
            portfolio_context = context.model_dump() if personalize else None
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

    # Phase 4: snapshot this prediction as a pending outcome for calibration.
    try:
        from app.calibration import create_pending_outcome

        create_pending_outcome(db, stored, report)
    except Exception as exc:  # noqa: BLE001 — calibration must never break a run
        logger.info("could not create outcome row for %s: %s", ticker, exc)

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
    market=None, llm=None, shared_cache: dict | None = None,
) -> list[StoredReport]:
    stored = []
    for ticker in tickers_for_user(db, user):
        result = run_summary_for_ticker(
            db, user, ticker, graph=graph, prices=prices, trigger=trigger,
            market=market, llm=llm, shared_cache=shared_cache,
        )
        if result is not None:
            stored.append(result)
    return stored
