"""Daily summary feed — stored reports, viewable without re-running agents.

Factory pattern (like the portfolio router): main.py injects the graph and
price provider so `POST /summaries/run` can trigger the exact same code path
the nightly job uses — essential for demoing without waiting until tomorrow.

Run-now is a background job with observable progress: POST returns a
`job_id` immediately and the run proceeds ticker-by-ticker in a worker
thread; `GET /summaries/run/{job_id}` reports completed/total + the ticker
currently being researched, so the UI can render a real progress bar.
Jobs are in-memory only (same lifetime rules as research runs).
"""
from __future__ import annotations

import json
import threading
import uuid
from dataclasses import dataclass, field

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.db import get_db
from app.db_models import StoredReport, User
from app.models import FinalReport, StoredReportOut, StoredReportSummary
from app.summaries import (
    run_summary_for_ticker,
    tickers_for_user,
    tickers_missing_today,
)
from app.tools.base import PriceHistoryProvider


@dataclass
class SummaryRunJob:
    """Progress of one manual run-now sweep (in-memory, user-scoped)."""

    id: str
    user_id: int
    tickers: list[str]
    completed: int = 0
    current: str | None = None
    status: str = "running"  # running | done | error
    results: list[StoredReportSummary] = field(default_factory=list)
    error: str | None = None

    def as_dict(self) -> dict:
        return {
            "job_id": self.id,
            "status": self.status,
            "total": len(self.tickers),
            "completed": self.completed,
            "current": self.current,
            "tickers": self.tickers,
            "results": [r.model_dump() for r in self.results],
            "error": self.error,
        }


_JOBS: dict[str, SummaryRunJob] = {}


def _summary_out(r: StoredReport) -> StoredReportSummary:
    return StoredReportSummary(
        id=r.id, ticker=r.ticker, stance=r.stance, confidence=r.confidence,
        summary=r.summary, trigger=r.trigger,
        created_at=r.created_at.isoformat() if r.created_at else "",
    )


def create_summaries_router(
    graph, prices: PriceHistoryProvider, session_factory=None
) -> APIRouter:
    """`session_factory` — worker threads need their own DB sessions (the
    request-scoped one closes when POST returns). Defaults to the app's
    SessionLocal; tests inject their own."""
    if session_factory is None:
        from app.db import SessionLocal as session_factory  # noqa: N813

    router = APIRouter(tags=["summaries"])

    def _run_job(job: SummaryRunJob) -> None:
        db = session_factory()
        try:
            user = db.get(User, job.user_id)
            for ticker in job.tickers:
                job.current = ticker
                stored = run_summary_for_ticker(
                    db, user, ticker, graph=graph, prices=prices,
                    trigger="manual",
                )
                if stored is not None:
                    job.results.append(_summary_out(stored))
                job.completed += 1
            job.status = "done"
        except Exception as exc:  # noqa: BLE001 — surface, don't crash the thread
            job.status = "error"
            job.error = str(exc)[:300]
        finally:
            job.current = None
            db.close()

    @router.get("/summaries", response_model=list[StoredReportSummary])
    def list_summaries(
        ticker: str | None = Query(None, max_length=12),
        limit: int = Query(50, ge=1, le=200),
        latest: bool = Query(
            False,
            description="Return only the newest summary per ticker "
            "(deduped feed view). History remains available without it.",
        ),
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        stmt = (
            select(StoredReport)
            .where(StoredReport.user_id == user.id)
            .order_by(StoredReport.created_at.desc(), StoredReport.id.desc())
            .limit(limit)
        )
        if ticker:
            stmt = stmt.where(StoredReport.ticker == ticker.strip().upper())
        rows = list(db.scalars(stmt))
        if latest:
            seen: set[str] = set()
            deduped = []
            for r in rows:  # already newest-first
                if r.ticker not in seen:
                    seen.add(r.ticker)
                    deduped.append(r)
            rows = deduped
        return [_summary_out(r) for r in rows]

    @router.get("/summaries/{summary_id}", response_model=StoredReportOut)
    def get_summary(
        summary_id: int,
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        row = db.get(StoredReport, summary_id)
        if row is None or row.user_id != user.id:
            raise HTTPException(status_code=404, detail="Summary not found.")
        try:
            report = FinalReport(**json.loads(row.report_json))
        except Exception:  # noqa: BLE001
            raise HTTPException(status_code=500, detail="Stored report unreadable.")
        return StoredReportOut(**_summary_out(row).model_dump(), report=report)

    @router.post("/summaries/run", status_code=202)
    def run_now(
        mode: str = Query(
            "all",
            pattern="^(missing|all)$",
            description="'missing' runs only tickers with no summary yet "
            "today (token-efficient — e.g. a newly added holding); "
            "'all' (default, backward-compatible) re-runs every "
            "watched/held ticker.",
        ),
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> dict:
        """Start a run-now sweep (same code path as the nightly job).
        Returns immediately with a job_id — poll
        `GET /summaries/run/{job_id}` for progress."""
        if not tickers_for_user(db, user):
            raise HTTPException(
                status_code=422,
                detail="Add tickers to your watchlist or portfolio first.",
            )
        tickers = (
            tickers_missing_today(db, user)
            if mode == "missing"
            else tickers_for_user(db, user)
        )
        if not tickers:
            # Everything already summarized today — nothing to spend tokens on.
            return {
                "job_id": None, "status": "done", "total": 0, "completed": 0,
                "current": None, "tickers": [], "results": [], "error": None,
            }
        # One sweep at a time per user — a second click just returns the
        # job that's already running.
        for job in _JOBS.values():
            if job.user_id == user.id and job.status == "running":
                return job.as_dict()

        job = SummaryRunJob(
            id=uuid.uuid4().hex[:12], user_id=user.id, tickers=tickers
        )
        _JOBS[job.id] = job
        threading.Thread(target=_run_job, args=(job,), daemon=True).start()
        return job.as_dict()

    @router.get("/summaries/run/{job_id}")
    def run_status(
        job_id: str,
        user: User = Depends(get_current_user),
    ) -> dict:
        job = _JOBS.get(job_id)
        if job is None or job.user_id != user.id:
            raise HTTPException(status_code=404, detail="Unknown job id.")
        return job.as_dict()

    return router
