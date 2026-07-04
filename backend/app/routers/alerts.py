"""Alert-rule configuration + in-app notification endpoints (all user-scoped)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.db import get_db
from app.db_models import AlertRule, Notification, User
from app.models import (
    ALERT_CONDITIONS,
    AlertRuleIn,
    AlertRuleOut,
    NotificationOut,
)

router = APIRouter(tags=["alerts"])


def _rule_out(r: AlertRule) -> AlertRuleOut:
    return AlertRuleOut(
        id=r.id, ticker=r.ticker, condition=r.condition,
        threshold=r.threshold, email=r.email, active=r.active,
    )


def _note_out(n: Notification) -> NotificationOut:
    return NotificationOut(
        id=n.id, ticker=n.ticker, condition=n.condition, title=n.title,
        body=n.body, report_id=n.report_id, read=n.read,
        created_at=n.created_at.isoformat() if n.created_at else "",
    )


# -- Alert rules ---------------------------------------------------------------
@router.get("/alerts", response_model=list[AlertRuleOut])
def list_rules(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    rules = db.scalars(
        select(AlertRule)
        .where(AlertRule.user_id == user.id)
        .order_by(AlertRule.ticker, AlertRule.condition)
    )
    return [_rule_out(r) for r in rules]


@router.post("/alerts", response_model=AlertRuleOut, status_code=201)
def upsert_rule(
    req: AlertRuleIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ticker = req.ticker.strip().upper()
    if not ticker.replace(".", "").replace("-", "").isalnum():
        raise HTTPException(status_code=422, detail="Invalid ticker symbol.")
    if req.condition not in ALERT_CONDITIONS:
        raise HTTPException(
            status_code=422, detail=f"condition must be one of {ALERT_CONDITIONS}"
        )
    if req.condition == "price_move" and req.threshold is not None:
        if not 0 < req.threshold <= 100:
            raise HTTPException(422, "price_move threshold must be 0–100 (%).")
    if req.condition == "high_confidence_claim" and req.threshold is not None:
        if not 0 < req.threshold <= 1:
            raise HTTPException(422, "confidence threshold must be 0–1.")

    existing = db.scalar(
        select(AlertRule).where(
            AlertRule.user_id == user.id,
            AlertRule.ticker == ticker,
            AlertRule.condition == req.condition,
        )
    )
    if existing:
        existing.threshold = req.threshold
        existing.email = req.email
        existing.active = req.active
        db.commit()
        return _rule_out(existing)
    rule = AlertRule(
        user_id=user.id, ticker=ticker, condition=req.condition,
        threshold=req.threshold, email=req.email, active=req.active,
    )
    db.add(rule)
    db.commit()
    return _rule_out(rule)


@router.delete("/alerts/{rule_id}", status_code=204)
def delete_rule(
    rule_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rule = db.get(AlertRule, rule_id)
    if rule is None or rule.user_id != user.id:
        raise HTTPException(status_code=404, detail="Alert rule not found.")
    db.delete(rule)
    db.commit()


# -- Notifications ---------------------------------------------------------------
@router.get("/notifications", response_model=list[NotificationOut])
def list_notifications(
    unread_only: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    stmt = (
        select(Notification)
        .where(Notification.user_id == user.id)
        .order_by(Notification.created_at.desc(), Notification.id.desc())
        .limit(limit)
    )
    if unread_only:
        stmt = stmt.where(Notification.read.is_(False))
    return [_note_out(n) for n in db.scalars(stmt)]


@router.get("/notifications/unread-count")
def unread_count(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    count = db.scalar(
        select(func.count(Notification.id)).where(
            Notification.user_id == user.id, Notification.read.is_(False)
        )
    )
    return {"unread": int(count or 0)}


@router.post("/notifications/{notification_id}/read", response_model=NotificationOut)
def mark_read(
    notification_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    note = db.get(Notification, notification_id)
    if note is None or note.user_id != user.id:
        raise HTTPException(status_code=404, detail="Notification not found.")
    note.read = True
    db.commit()
    return _note_out(note)


@router.post("/notifications/read-all")
def mark_all_read(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    db.execute(
        update(Notification)
        .where(Notification.user_id == user.id, Notification.read.is_(False))
        .values(read=True)
    )
    db.commit()
    return {"ok": True}
