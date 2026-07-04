"""Watchlist CRUD — tickers a user tracks independently of holdings.

All endpoints are scoped to the logged-in user (same pattern as portfolio).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.db import get_db
from app.db_models import User, WatchlistItem
from app.models import WatchlistItemIn, WatchlistItemOut

router = APIRouter(tags=["watchlist"])


def _out(w: WatchlistItem) -> WatchlistItemOut:
    return WatchlistItemOut(
        id=w.id, ticker=w.ticker, note=w.note,
        created_at=w.created_at.isoformat() if w.created_at else "",
    )


def _normalize_ticker(raw: str) -> str:
    ticker = raw.strip().upper()
    if not ticker or not ticker.replace(".", "").replace("-", "").isalnum():
        raise HTTPException(status_code=422, detail="Invalid ticker symbol.")
    return ticker


@router.get("/watchlist", response_model=list[WatchlistItemOut])
def list_watchlist(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    items = db.scalars(
        select(WatchlistItem)
        .where(WatchlistItem.user_id == user.id)
        .order_by(WatchlistItem.ticker)
    )
    return [_out(w) for w in items]


@router.post("/watchlist", response_model=WatchlistItemOut, status_code=201)
def add_to_watchlist(
    req: WatchlistItemIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ticker = _normalize_ticker(req.ticker)
    existing = db.scalar(
        select(WatchlistItem).where(
            WatchlistItem.user_id == user.id, WatchlistItem.ticker == ticker
        )
    )
    if existing:  # idempotent upsert — just refresh the note
        existing.note = req.note
        db.commit()
        return _out(existing)
    item = WatchlistItem(user_id=user.id, ticker=ticker, note=req.note)
    db.add(item)
    db.commit()
    return _out(item)


@router.delete("/watchlist/{item_id}", status_code=204)
def remove_from_watchlist(
    item_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    item = db.get(WatchlistItem, item_id)
    if item is None or item.user_id != user.id:
        raise HTTPException(status_code=404, detail="Watchlist item not found.")
    db.delete(item)
    db.commit()
