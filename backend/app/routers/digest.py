"""Email digest preferences — GET/PUT settings + a send-now demo endpoint."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.db import get_db
from app.db_models import EmailDigestPreference, User
from app.digest import send_digest_for_user
from app.models import DIGEST_FREQUENCIES, DigestPreferenceIn, DigestPreferenceOut

router = APIRouter(tags=["digest"])


def _out(pref: EmailDigestPreference | None) -> DigestPreferenceOut:
    if pref is None:
        return DigestPreferenceOut()  # disabled defaults
    return DigestPreferenceOut(
        enabled=pref.enabled,
        frequency=pref.frequency,
        weekday=pref.weekday,
        last_sent_at=pref.last_sent_at.isoformat() if pref.last_sent_at else None,
    )


@router.get("/digest", response_model=DigestPreferenceOut)
def get_digest_prefs(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    pref = db.scalar(
        select(EmailDigestPreference).where(
            EmailDigestPreference.user_id == user.id
        )
    )
    return _out(pref)


@router.put("/digest", response_model=DigestPreferenceOut)
def put_digest_prefs(
    req: DigestPreferenceIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if req.frequency not in DIGEST_FREQUENCIES:
        raise HTTPException(
            422, f"frequency must be one of {DIGEST_FREQUENCIES}"
        )
    if req.frequency == "weekly" and req.weekday is None:
        raise HTTPException(422, "weekly digests need a weekday (0=Mon … 6=Sun).")

    pref = db.scalar(
        select(EmailDigestPreference).where(
            EmailDigestPreference.user_id == user.id
        )
    )
    if pref is None:
        pref = EmailDigestPreference(user_id=user.id)
        db.add(pref)
    pref.enabled = req.enabled
    pref.frequency = req.frequency
    pref.weekday = req.weekday if req.frequency == "weekly" else None
    db.commit()
    return _out(pref)


@router.post("/digest/send-now")
def send_digest_now(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    """Send the digest immediately, ignoring the schedule — lets users preview
    what they'll receive (console-logged in dev when SMTP isn't configured)."""
    sent = send_digest_for_user(db, user, force=True)
    if not sent:
        raise HTTPException(
            status_code=422,
            detail="No stored summaries to digest yet — run the daily feed "
                   "first (Daily Feed → Run now).",
        )
    return {"sent": True}
