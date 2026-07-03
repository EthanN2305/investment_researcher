"""Portfolio & preferences CRUD — all endpoints scoped to the logged-in user.

Factory pattern: main.py injects the market-data provider so we can capture
a holding's sector once at insert time (best-effort) instead of doing N live
lookups on every personalized research run.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.db import get_db
from app.db_models import Holding, Preferences, User
from app.models import (
    HORIZONS,
    LEANS,
    RISK_TOLERANCES,
    HoldingIn,
    HoldingOut,
    PortfolioContext,
    PreferencesIn,
    PreferencesOut,
)
from app.tools.base import MarketDataProvider

logger = logging.getLogger("portfolio")


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


def create_portfolio_router(market: MarketDataProvider) -> APIRouter:
    router = APIRouter(tags=["portfolio"])

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
