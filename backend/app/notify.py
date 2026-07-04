"""Notification delivery — in-app rows + best-effort email.

In-app is the source of truth (a `Notification` row is always written).
Email is the stretch channel: sent via SMTP when configured, otherwise
logged to the console so dev runs still show what *would* have been sent.
"""
from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from sqlalchemy.orm import Session

from app.config import settings
from app.db_models import Notification, User

logger = logging.getLogger("notify")


def create_notification(
    db: Session,
    user: User,
    *,
    ticker: str,
    condition: str,
    title: str,
    body: str = "",
    report_id: int | None = None,
    send_email_too: bool = False,
) -> Notification:
    """Persist an in-app notification; optionally mirror it to email."""
    note = Notification(
        user_id=user.id, ticker=ticker, condition=condition,
        title=title[:200], body=body[:1000], report_id=report_id,
    )
    db.add(note)
    db.commit()
    if send_email_too:
        send_email(user.email, f"[Investment Research] {title}", body or title)
    return note


def send_email(to: str, subject: str, body: str) -> bool:
    """Send via SMTP if configured; console fallback otherwise.

    Returns True only when an SMTP send succeeded. Failures never raise —
    alerting must not break the daily job.
    """
    if not settings.smtp_host:
        logger.info(
            "EMAIL (console fallback — no SMTP_HOST configured)\n"
            "  To: %s\n  Subject: %s\n  Body: %s", to, subject, body,
        )
        return False
    try:
        msg = EmailMessage()
        msg["From"] = settings.smtp_from or settings.smtp_user or "noreply@localhost"
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body)
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as s:
            s.ehlo()
            if settings.smtp_starttls:
                s.starttls()
            if settings.smtp_user:
                s.login(settings.smtp_user, settings.smtp_password)
            s.send_message(msg)
        return True
    except Exception as exc:  # noqa: BLE001 — email is best-effort
        logger.warning("email to %s failed: %s", to, exc)
        return False
