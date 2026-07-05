"""Top-stock recommendations — global ranked picks from the index universe.

GET  /recommendations           → latest stored top-10 (instant, no agents)
POST /recommendations/run       → start a sweep in a worker thread; job_id back
GET  /recommendations/run/{id}  → screen/analyze progress for the UI bar

A sweep screens the S&P 500 + Nasdaq-100 on technicals (no penny stocks),
then runs the quick agent pipeline on the survivors — same job pattern as
the summaries run-now endpoint. One sweep at a time, results are global
(every signed-in user sees the same board).
"""
from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.db import get_db
from app.db_models import RecommendationItem, User
from app.recommender import run_recommendations
from app.universe import UNIVERSE


class RecommendationOut(BaseModel):
    rank: int
    ticker: str
    price: float | None = None
    screen_score: float
    momentum_3mo: float | None = None
    stance: str
    confidence: float
    summary: str
    created_at: str


class RecommendationsResponse(BaseModel):
    run_id: str | None = None
    created_at: str | None = None
    universe_size: int = len(UNIVERSE)
    items: list[RecommendationOut] = []


@dataclass
class RecommendationJob:
    id: str
    phase: str = "screening"  # screening | analyzing | done | error
    completed: int = 0
    total: int = 0
    current: str | None = None
    status: str = "running"  # running | done | error
    error: str | None = None

    def as_dict(self) -> dict:
        return {
            "job_id": self.id,
            "status": self.status,
            "phase": self.phase,
            "completed": self.completed,
            "total": self.total,
            "current": self.current,
            "error": self.error,
        }


_JOBS: dict[str, RecommendationJob] = {}
_RUN_LOCK = threading.Lock()


def _item_out(r: RecommendationItem) -> RecommendationOut:
    return RecommendationOut(
        rank=r.rank, ticker=r.ticker, price=r.price,
        screen_score=r.screen_score, momentum_3mo=r.momentum_3mo,
        stance=r.stance, confidence=r.confidence, summary=r.summary,
        created_at=r.created_at.isoformat() if r.created_at else "",
    )


def create_recommendations_router(graph, session_factory=None) -> APIRouter:
    if session_factory is None:
        from app.db import SessionLocal as session_factory  # noqa: N813

    router = APIRouter(tags=["recommendations"])

    def _run_job(job: RecommendationJob) -> None:
        db = session_factory()
        try:
            def progress(phase: str, completed: int, total: int,
                         current: str | None) -> None:
                job.phase = phase
                job.completed = completed
                job.total = total
                job.current = current

            run_recommendations(db, graph, progress=progress)
            job.phase = "done"
            job.status = "done"
        except Exception as exc:  # noqa: BLE001 — surface, don't crash the thread
            job.phase = "error"
            job.status = "error"
            job.error = str(exc)[:300]
        finally:
            job.current = None
            db.close()

    @router.get("/recommendations", response_model=RecommendationsResponse)
    def latest_recommendations(
        user: User = Depends(get_current_user), db: Session = Depends(get_db)
    ):
        newest = db.scalar(
            select(RecommendationItem)
            .order_by(
                RecommendationItem.created_at.desc(),
                RecommendationItem.id.desc(),
            )
            .limit(1)
        )
        if newest is None:
            return RecommendationsResponse()
        items = db.scalars(
            select(RecommendationItem)
            .where(RecommendationItem.run_id == newest.run_id)
            .order_by(RecommendationItem.rank.asc())
        ).all()
        return RecommendationsResponse(
            run_id=newest.run_id,
            created_at=newest.created_at.isoformat() if newest.created_at else None,
            items=[_item_out(r) for r in items],
        )

    @router.post("/recommendations/run", status_code=202)
    def start_run(user: User = Depends(get_current_user)) -> dict:
        with _RUN_LOCK:
            if any(j.status == "running" for j in _JOBS.values()):
                raise HTTPException(
                    409, "A recommendations sweep is already running."
                )
            job = RecommendationJob(id=uuid.uuid4().hex[:12], total=len(UNIVERSE))
            _JOBS[job.id] = job
        threading.Thread(
            target=_run_job, args=(job,), name=f"recs-{job.id}", daemon=True
        ).start()
        return job.as_dict()

    @router.get("/recommendations/run/{job_id}")
    def run_status(job_id: str, user: User = Depends(get_current_user)) -> dict:
        job = _JOBS.get(job_id)
        if job is None:
            raise HTTPException(404, "Unknown job id.")
        return job.as_dict()

    return router
