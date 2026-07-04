"""Alert evaluation — runs after each stored daily/manual report.

Three conditions (Phase 4 scope):

  price_move             |1-day % change| ≥ threshold (default 5%)
  high_confidence_claim  a claim with confidence ≥ threshold (default 0.85)
                         that was NOT in the previous stored report
  negative_news          a news-agent claim matching negative keywords that
                         was NOT in the previous stored report

"New vs previous report" comparison keeps daily alerts from re-firing on the
same claim every day. The negative-news check is a keyword heuristic —
deliberately simple and transparent rather than another LLM call.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db_models import AlertRule, User
from app.models import ALERT_DEFAULT_THRESHOLDS, FinalReport
from app.notify import create_notification
from app.tools.base import PriceHistoryProvider

logger = logging.getLogger("alerts")

NEGATIVE_KEYWORDS = (
    "lawsuit", "investigation", "probe", "recall", "layoff", "miss", "missed",
    "decline", "declined", "drop", "dropped", "fell", "plunge", "downgrade",
    "warning", "fraud", "delay", "delayed", "loss", "losses", "cut", "bankrupt",
    "sell-off", "selloff", "weak", "underperform", "negative",
)


@dataclass
class Triggered:
    condition: str
    title: str
    body: str


def _claim_texts(report: FinalReport | None) -> set[str]:
    if report is None:
        return set()
    return {
        c.claim.strip().lower()
        for r in report.agent_reports
        for c in r.claims
    }


def _is_negative(text: str) -> bool:
    lowered = text.lower()
    return any(kw in lowered for kw in NEGATIVE_KEYWORDS)


def latest_price_move_pct(prices: PriceHistoryProvider, ticker: str) -> float | None:
    """% change between the last two daily closes; None when unavailable."""
    try:
        history = prices.get_history(ticker, period="5d")
    except Exception as exc:  # noqa: BLE001 — price feed is best-effort
        logger.info("price history for %s unavailable: %s", ticker, exc)
        return None
    closes = history.closes
    if len(closes) < 2 or closes[-2] == 0:
        return None
    return (closes[-1] - closes[-2]) / closes[-2] * 100.0


def evaluate_rules(
    *,
    ticker: str,
    rules: list[AlertRule],
    report: FinalReport,
    previous_report: FinalReport | None,
    price_move_pct: float | None,
) -> list[Triggered]:
    """Pure evaluation — no DB writes, easy to unit-test."""
    triggered: list[Triggered] = []
    known_claims = _claim_texts(previous_report)

    for rule in rules:
        if not rule.active:
            continue
        threshold = (
            rule.threshold
            if rule.threshold is not None
            else ALERT_DEFAULT_THRESHOLDS.get(rule.condition)
        )

        if rule.condition == "price_move":
            if price_move_pct is None or threshold is None:
                continue
            if abs(price_move_pct) >= threshold:
                direction = "up" if price_move_pct > 0 else "down"
                triggered.append(Triggered(
                    "price_move",
                    f"{ticker} moved {direction} {abs(price_move_pct):.1f}% today",
                    f"Daily move of {price_move_pct:+.1f}% crossed your "
                    f"±{threshold:g}% alert threshold.",
                ))

        elif rule.condition == "high_confidence_claim":
            if threshold is None:
                continue
            fresh = [
                c
                for r in report.agent_reports
                for c in r.claims
                if c.confidence >= threshold
                and c.claim.strip().lower() not in known_claims
            ]
            if fresh:
                top = max(fresh, key=lambda c: c.confidence)
                triggered.append(Triggered(
                    "high_confidence_claim",
                    f"New high-confidence claim on {ticker} "
                    f"({top.confidence:.0%})",
                    f"“{top.claim}” — {top.evidence} (source: {top.source})",
                ))

        elif rule.condition == "negative_news":
            news = next(
                (r for r in report.agent_reports if r.agent == "news"), None
            )
            fresh_negative = [
                c for c in (news.claims if news else [])
                if _is_negative(c.claim)
                and c.claim.strip().lower() not in known_claims
            ]
            if fresh_negative:
                worst = fresh_negative[0]
                triggered.append(Triggered(
                    "negative_news",
                    f"Negative news on {ticker}",
                    f"“{worst.claim}” (source: {worst.source})"
                    + (f" — and {len(fresh_negative) - 1} more"
                       if len(fresh_negative) > 1 else ""),
                ))

    return triggered


def process_alerts_for_report(
    db: Session,
    user: User,
    *,
    ticker: str,
    report: FinalReport,
    previous_report: FinalReport | None,
    prices: PriceHistoryProvider,
    report_id: int | None = None,
) -> int:
    """Evaluate the user's rules for this ticker and write notifications."""
    rules = list(db.scalars(
        select(AlertRule).where(
            AlertRule.user_id == user.id, AlertRule.ticker == ticker
        )
    ))
    if not rules:
        return 0

    needs_price = any(r.condition == "price_move" and r.active for r in rules)
    move = latest_price_move_pct(prices, ticker) if needs_price else None

    fired = evaluate_rules(
        ticker=ticker, rules=rules, report=report,
        previous_report=previous_report, price_move_pct=move,
    )
    email_conditions = {r.condition for r in rules if r.email}
    for t in fired:
        create_notification(
            db, user,
            ticker=ticker, condition=t.condition, title=t.title, body=t.body,
            report_id=report_id,
            send_email_too=t.condition in email_conditions,
        )
    return len(fired)
