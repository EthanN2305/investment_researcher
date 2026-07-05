"""Portfolio & preferences CRUD — all endpoints scoped to the logged-in user.

Factory pattern: main.py injects the market-data provider so we can capture
a holding's sector once at insert time (best-effort) instead of doing N live
lookups on every personalized research run.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.db import get_db
from app.db_models import Holding, Preferences, StoredReport, User
from app.models import (
    HORIZONS,
    LEANS,
    RISK_TOLERANCES,
    HoldingIn,
    HoldingOut,
    PortfolioContext,
    PreferencesIn,
    PreferencesOut,
    PriceHistory,
)
from app.tools.base import MarketDataProvider, PriceHistoryProvider

logger = logging.getLogger("portfolio")

# -- Valuation response models ---------------------------------------------------

VALUATION_PERIODS = ("1mo", "3mo", "6mo", "1y", "2y", "5y")
_PERIOD_DAYS = {"1mo": 31, "3mo": 92, "6mo": 183, "1y": 366, "2y": 731, "5y": 1827}


class HoldingValuation(BaseModel):
    id: int
    ticker: str
    quantity: float
    cost_basis: float
    sector: str | None = None
    price: float | None = None          # latest close; None if lookup failed
    value: float | None = None          # quantity * price
    cost_value: float
    gain: float | None = None           # value - cost_value
    gain_pct: float | None = None       # gain / cost_value * 100
    day_change_pct: float | None = None  # last close vs. previous close
    price_source: str | None = None      # "live" | "summary" | None
    price_as_of: str | None = None       # date of the price used


class PortfolioSeries(BaseModel):
    dates: list[str] = []
    values: list[float] = []


class PortfolioValuation(BaseModel):
    period: str
    total_value: float
    total_cost: float
    total_gain: float
    total_gain_pct: float | None = None
    day_change: float | None = None
    day_change_pct: float | None = None
    holdings: list[HoldingValuation] = []
    history: PortfolioSeries = PortfolioSeries()
    errors: list[str] = []              # tickers whose price lookup failed


def _holding_out(h: Holding) -> HoldingOut:
    return HoldingOut(
        id=h.id, ticker=h.ticker, quantity=h.quantity,
        cost_basis=h.cost_basis, sector=h.sector,
    )


def _prefs_out(p: Preferences | None) -> PreferencesOut | None:
    if p is None:
        return None
    sectors = [s.strip() for s in (p.sector_interests or "").split(",") if s.strip()]
    return PreferencesOut(
        risk_tolerance=p.risk_tolerance,
        sector_interests=sectors,
        growth_value_lean=p.growth_value_lean,
        time_horizon=p.time_horizon,
    )


def load_portfolio_context(db: Session, user: User) -> PortfolioContext:
    """Snapshot used by the research pipeline (read-only)."""
    holdings = db.scalars(
        select(Holding).where(Holding.user_id == user.id).order_by(Holding.ticker)
    ).all()
    prefs = db.scalar(select(Preferences).where(Preferences.user_id == user.id))
    return PortfolioContext(
        user_email=user.email,
        holdings=[_holding_out(h) for h in holdings],
        preferences=_prefs_out(prefs),
    )


def create_portfolio_router(
    market: MarketDataProvider, prices: PriceHistoryProvider | None = None
) -> APIRouter:
    router = APIRouter(tags=["portfolio"])

    # Small in-process TTL cache so switching tabs doesn't hammer yfinance.
    _history_cache: dict[tuple[str, str], tuple[float, PriceHistory]] = {}
    _CACHE_TTL = 15 * 60  # seconds

    def _cached_history(ticker: str, period: str) -> PriceHistory:
        key = (ticker, period)
        hit = _history_cache.get(key)
        if hit and time.monotonic() - hit[0] < _CACHE_TTL:
            return hit[1]
        history = prices.get_history(ticker, period=period)
        _history_cache[key] = (time.monotonic(), history)
        return history

    def _summary_history(
        db: Session, user_id: int, ticker: str, period: str
    ) -> PriceHistory | None:
        """Fallback price series built from stored daily-summary reports.

        Each summary stores the close the Technical Analysis Agent saw
        (e.g. "close=359.91"), so even when the live quote feed is down or
        rate-limited, the portfolio can be valued at summary prices. Older
        rows written before the `price` column existed are parsed from
        their report JSON and backfilled.
        """
        rows = db.scalars(
            select(StoredReport)
            .where(
                StoredReport.user_id == user_id,
                StoredReport.ticker == ticker,
            )
            .order_by(StoredReport.created_at.asc(), StoredReport.id.asc())
        ).all()
        if not rows:
            return None

        # Lazy import: app.summaries imports this module at load time.
        from app.models import FinalReport
        from app.summaries import extract_price_from_report

        by_date: dict[str, float] = {}
        backfilled = False
        for row in rows:
            price = row.price
            if price is None:
                try:
                    price = extract_price_from_report(
                        FinalReport(**json.loads(row.report_json))
                    )
                except Exception:  # noqa: BLE001 — corrupt old row
                    price = None
                if price is not None:
                    row.price = price
                    backfilled = True
            if price is not None:
                by_date[row.created_at.strftime("%Y-%m-%d")] = price
        if backfilled:
            db.commit()
        if not by_date:
            return None

        cutoff = (
            datetime.utcnow() - timedelta(days=_PERIOD_DAYS[period])
        ).strftime("%Y-%m-%d")
        dates = sorted(d for d in by_date if d >= cutoff)
        if not dates:  # keep at least the most recent snapshot
            dates = [max(by_date)]
        return PriceHistory(
            ticker=ticker,
            dates=dates,
            closes=[by_date[d] for d in dates],
            source="research summaries",
        )

    def _lookup_sector(ticker: str) -> str | None:
        try:
            return market.get_market_data(ticker).sector
        except Exception as exc:  # noqa: BLE001 — sector is a nice-to-have
            logger.info("sector lookup failed for %s: %s", ticker, exc)
            return None

    # -- Holdings --------------------------------------------------------------
    @router.get("/portfolio", response_model=list[HoldingOut])
    def list_holdings(
        user: User = Depends(get_current_user), db: Session = Depends(get_db)
    ):
        return [
            _holding_out(h)
            for h in db.scalars(
                select(Holding)
                .where(Holding.user_id == user.id)
                .order_by(Holding.ticker)
            )
        ]

    @router.post("/portfolio", response_model=HoldingOut, status_code=201)
    def upsert_holding(
        req: HoldingIn,
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        ticker = req.ticker.strip().upper()
        if not ticker.replace(".", "").replace("-", "").isalnum():
            raise HTTPException(status_code=422, detail="Invalid ticker symbol.")
        existing = db.scalar(
            select(Holding).where(Holding.user_id == user.id, Holding.ticker == ticker)
        )
        if existing:
            existing.quantity = req.quantity
            existing.cost_basis = req.cost_basis
            if existing.sector is None:
                existing.sector = _lookup_sector(ticker)
            db.commit()
            return _holding_out(existing)
        holding = Holding(
            user_id=user.id, ticker=ticker, quantity=req.quantity,
            cost_basis=req.cost_basis, sector=_lookup_sector(ticker),
        )
        db.add(holding)
        db.commit()
        return _holding_out(holding)

    # -- Live valuation ----------------------------------------------------------
    @router.get("/portfolio/valuation", response_model=PortfolioValuation)
    def portfolio_valuation(
        period: str = Query("6mo"),
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        """Current prices, gain/loss, and a portfolio-value time series.

        The series sums quantity x close per day, forward-filling each
        ticker's last known close across missing dates. It starts at the
        latest first-trade date across holdings so early dates aren't
        artificially missing positions.
        """
        if period not in VALUATION_PERIODS:
            raise HTTPException(
                422, f"period must be one of {', '.join(VALUATION_PERIODS)}"
            )
        if prices is None:
            raise HTTPException(503, "Price history provider not configured.")

        holdings = db.scalars(
            select(Holding)
            .where(Holding.user_id == user.id)
            .order_by(Holding.ticker)
        ).all()

        histories: dict[str, PriceHistory] = {}
        sources: dict[str, str] = {}  # ticker -> "live" | "summary"
        errors: list[str] = []
        for h in holdings:
            if h.ticker in histories or h.ticker in errors:
                continue
            try:
                histories[h.ticker] = _cached_history(h.ticker, period)
                sources[h.ticker] = "live"
                continue
            except Exception as exc:  # noqa: BLE001 — degrade per ticker
                logger.warning("valuation: history failed for %s: %s", h.ticker, exc)
            # Fallback: prices captured by the daily-summary agent runs.
            fallback = _summary_history(db, user.id, h.ticker, period)
            if fallback is not None:
                histories[h.ticker] = fallback
                sources[h.ticker] = "summary"
            else:
                errors.append(h.ticker)

        out: list[HoldingValuation] = []
        total_value = 0.0
        total_cost = 0.0
        for h in holdings:
            cost_value = h.quantity * h.cost_basis
            total_cost += cost_value
            hv = HoldingValuation(
                id=h.id, ticker=h.ticker, quantity=h.quantity,
                cost_basis=h.cost_basis, sector=h.sector, cost_value=cost_value,
            )
            history = histories.get(h.ticker)
            if history and history.closes:
                price = history.closes[-1]
                hv.price = round(price, 4)
                hv.value = round(h.quantity * price, 2)
                hv.gain = round(hv.value - cost_value, 2)
                hv.gain_pct = (
                    round(hv.gain / cost_value * 100, 2) if cost_value else None
                )
                if len(history.closes) >= 2 and history.closes[-2]:
                    hv.day_change_pct = round(
                        (price / history.closes[-2] - 1) * 100, 2
                    )
                hv.price_source = sources.get(h.ticker)
                hv.price_as_of = history.dates[-1] if history.dates else None
                total_value += hv.value
            out.append(hv)

        # -- Portfolio value series (union of dates, forward-filled) --------
        dates_out: list[str] = []
        values_out: list[float] = []
        if histories:
            per_ticker = {
                t: dict(zip(ph.dates, ph.closes)) for t, ph in histories.items()
            }
            start = max(ph.dates[0] for ph in histories.values() if ph.dates)
            all_dates = sorted({d for ph in histories.values() for d in ph.dates})
            last_close: dict[str, float] = {}
            qty_by_ticker: dict[str, float] = {}
            for h in holdings:
                if h.ticker in histories:
                    qty_by_ticker[h.ticker] = (
                        qty_by_ticker.get(h.ticker, 0.0) + h.quantity
                    )
            for d in all_dates:
                for t, closes in per_ticker.items():
                    if d in closes:
                        last_close[t] = closes[d]
                if d < start or len(last_close) < len(per_ticker):
                    continue
                dates_out.append(d)
                values_out.append(
                    round(
                        sum(qty_by_ticker[t] * last_close[t] for t in per_ticker), 2
                    )
                )

        day_change = day_change_pct = None
        if len(values_out) >= 2 and values_out[-2]:
            day_change = round(values_out[-1] - values_out[-2], 2)
            day_change_pct = round((values_out[-1] / values_out[-2] - 1) * 100, 2)

        total_gain = round(total_value - total_cost, 2)
        return PortfolioValuation(
            period=period,
            total_value=round(total_value, 2),
            total_cost=round(total_cost, 2),
            total_gain=total_gain,
            total_gain_pct=(
                round(total_gain / total_cost * 100, 2) if total_cost else None
            ),
            day_change=day_change,
            day_change_pct=day_change_pct,
            holdings=out,
            history=PortfolioSeries(dates=dates_out, values=values_out),
            errors=errors,
        )

    @router.delete("/portfolio/{holding_id}", status_code=204)
    def delete_holding(
        holding_id: int,
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        holding = db.get(Holding, holding_id)
        if holding is None or holding.user_id != user.id:
            raise HTTPException(status_code=404, detail="Holding not found.")
        db.delete(holding)
        db.commit()

    # -- Preferences -----------------------------------------------------------
    @router.get("/preferences", response_model=PreferencesOut)
    def get_preferences(
        user: User = Depends(get_current_user), db: Session = Depends(get_db)
    ):
        prefs = db.scalar(select(Preferences).where(Preferences.user_id == user.id))
        return _prefs_out(prefs) or PreferencesOut()

    @router.put("/preferences", response_model=PreferencesOut)
    def put_preferences(
        req: PreferencesIn,
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        if req.risk_tolerance and req.risk_tolerance not in RISK_TOLERANCES:
            raise HTTPException(422, f"risk_tolerance must be one of {RISK_TOLERANCES}")
        if req.growth_value_lean and req.growth_value_lean not in LEANS:
            raise HTTPException(422, f"growth_value_lean must be one of {LEANS}")
        if req.time_horizon and req.time_horizon not in HORIZONS:
            raise HTTPException(422, f"time_horizon must be one of {HORIZONS}")

        prefs = db.scalar(select(Preferences).where(Preferences.user_id == user.id))
        if prefs is None:
            prefs = Preferences(user_id=user.id)
            db.add(prefs)
        prefs.risk_tolerance = req.risk_tolerance
        prefs.sector_interests = ",".join(
            s.strip() for s in req.sector_interests if s.strip()
        )
        prefs.growth_value_lean = req.growth_value_lean
        prefs.time_horizon = req.time_horizon
        db.commit()
        return _prefs_out(prefs)

    return router
