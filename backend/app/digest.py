"""Email digest — mails a user their daily feed on their chosen cadence.

Frequencies: daily (every sweep), weekly (on the user's chosen weekday),
monthly (1st of the month). The daily-summary sweep calls
`send_digest_if_due()` per user right after storing that user's fresh
reports, so the digest always reflects the newest data. `last_sent_at`
dedupes: a second sweep on the same UTC day never re-sends.

Delivery goes through app.notify.send_email — SMTP when configured,
console fallback in dev.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db_models import EmailDigestPreference, StoredReport, User
from app.notify import send_email

logger = logging.getLogger("digest")

WEEKDAY_NAMES = (
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
)


def get_or_default(db: Session, user: User) -> EmailDigestPreference | None:
    return db.scalar(
        select(EmailDigestPreference).where(
            EmailDigestPreference.user_id == user.id
        )
    )


def is_due(pref: EmailDigestPreference | None, now: datetime) -> bool:
    """Should a digest go out at `now` (UTC), given the user's settings?"""
    if pref is None or not pref.enabled:
        return False
    last = pref.last_sent_at
    if last is not None and last.date() == now.date():
        return False  # already sent today (sweep re-run, manual send, …)
    if pref.frequency == "daily":
        return True
    if pref.frequency == "weekly":
        return now.weekday() == (pref.weekday if pref.weekday is not None else 0)
    if pref.frequency == "monthly":
        return now.day == 1
    return False


def latest_summaries(db: Session, user: User) -> list[StoredReport]:
    """Newest stored report per ticker, for the user's current tickers."""
    # Local import: app.summaries pulls in the routers package, which imports
    # this module — importing it lazily keeps the module graph acyclic.
    from app.summaries import tickers_for_user

    tickers = tickers_for_user(db, user)
    out: list[StoredReport] = []
    for ticker in tickers:
        row = db.scalar(
            select(StoredReport)
            .where(StoredReport.user_id == user.id,
                   StoredReport.ticker == ticker)
            .order_by(StoredReport.created_at.desc(), StoredReport.id.desc())
            .limit(1)
        )
        if row is not None:
            out.append(row)
    return out


def build_digest(summaries: list[StoredReport], now: datetime) -> tuple[str, str]:
    """(subject, plain-text body) for the digest email."""
    try:
        date_str = now.strftime("%B %-d, %Y")
    except ValueError:  # Windows strftime lacks %-d
        date_str = now.strftime("%B %d, %Y")
    subject = f"Your investment digest — {date_str}"

    lines = [
        f"Daily feed digest for {date_str}",
        f"{len(summaries)} ticker(s) covered.",
        "",
    ]
    for s in summaries:
        pct = round((s.confidence or 0) * 100)
        lines.append(f"{s.ticker} — {s.stance.upper()} ({pct}% confidence)")
        if s.summary:
            lines.append(f"  {s.summary}")
        lines.append("")
    lines.append("Open the app's Daily Feed tab for the full structured reports.")
    lines.append("Informational research only — not investment advice.")
    return subject, "\n".join(lines)


def send_digest_for_user(
    db: Session, user: User, *, now: datetime | None = None, force: bool = False
) -> bool:
    """Send the digest if due (or `force`d). Returns True when a send happened
    (including the dev console fallback); False when skipped."""
    now = now or datetime.now(timezone.utc)
    pref = get_or_default(db, user)
    if not force and not is_due(pref, now):
        return False

    summaries = latest_summaries(db, user)
    if not summaries:
        logger.info("digest for %s skipped — no stored summaries", user.email)
        return False

    subject, body = build_digest(summaries, now)
    send_email(user.email, subject, body)  # console fallback counts as sent
    if pref is not None:
        pref.last_sent_at = now
        db.commit()
    logger.info("digest emailed to %s (%d tickers)", user.email, len(summaries))
    return True


def send_digest_if_due(db: Session, user: User, *, now: datetime | None = None) -> bool:
    try:
        return send_digest_for_user(db, user, now=now)
    except Exception as exc:  # noqa: BLE001 — digests must not break the sweep
        logger.warning("digest for %s failed: %s", user.email, exc)
        return False
