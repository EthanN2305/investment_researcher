"""FastAPI app for Phase 3 — multi-agent research with accounts & portfolios.

Flow:
  POST /research                  → start a run, returns {run_id}; if the
                                    caller is logged in (Bearer token) and
                                    personalize=true, the Portfolio Manager
                                    Agent joins the plan
  GET  /research/{run_id}/events  → SSE stream of per-agent progress,
                                    clarifying questions, and the final report
  POST /research/{run_id}/answer  → answer a clarifying question; the paused
                                    LangGraph run resumes from its checkpoint

Phase 3 additions: /auth/* (sign-up/login, JWT), /portfolio and /preferences
CRUD (SQLite via SQLAlchemy). Runs themselves remain in-memory.
"""
from __future__ import annotations

import logging

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import get_optional_user
from app.config import settings
from app.db import get_db, init_db
from app.db_models import User
from app.graph import build_graph
from app.routers import auth_router, create_portfolio_router
from app.routers.portfolio import load_portfolio_context
from app.runs import RunManager
from app.tools import (
    AnthropicAgentLLM,
    NewsAPINews,
    SecEdgarFinancials,
    YFinanceMarketData,
    YFinancePriceHistory,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("api")

app = FastAPI(
    title="AI Investment Research Analyst — Phase 3",
    version="0.3.0",
    description=(
        "Multi-agent research: planner-orchestrated News, Financial Statement, "
        "Valuation, and Technical Analysis agents with a Recommendation synthesis. "
        "Phase 3 adds accounts, stored portfolios/preferences, and a Portfolio "
        "Manager Agent that personalizes the report for logged-in users."
    ),
)

init_db()  # create SQLite tables on boot (idempotent)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Graph + run manager are process-wide singletons. The LLM provider is lenient
# about missing keys (agents fail soft with flags), so this always boots.
_market = YFinanceMarketData()
_graph = build_graph(
    market=_market,
    news=NewsAPINews(),
    financials=SecEdgarFinancials(),
    prices=YFinancePriceHistory(),
    llm=AnthropicAgentLLM(),
)
runs = RunManager(_graph)

# Phase 3 routers: auth + portfolio/preferences CRUD.
app.include_router(auth_router)
app.include_router(create_portfolio_router(_market))


class StartRequest(BaseModel):
    ticker: str = Field(..., min_length=1, max_length=12)
    depth: str | None = Field(None, description="'quick' | 'deep' | None (planner asks)")
    lens: str | None = Field(None, description="'growth' | 'value' | 'balanced'")
    personalize: bool = Field(
        True,
        description="When logged in, include the Portfolio Manager Agent. "
        "Ignored for anonymous requests.",
    )


class AnswerRequest(BaseModel):
    answer: str = Field(..., min_length=1, max_length=200)


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "phase": 3,
        "anthropic_key_set": bool(settings.anthropic_api_key),
        "newsapi_key_set": bool(settings.newsapi_key),
    }


@app.post("/research")
def start_research(
    req: StartRequest,
    user: User | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
) -> dict:
    ticker = req.ticker.strip().upper()
    if not ticker or not ticker.replace(".", "").replace("-", "").isalnum():
        raise HTTPException(status_code=422, detail="Invalid ticker symbol.")
    depth = req.depth.lower() if req.depth else None
    if depth is not None and depth not in ("quick", "deep"):
        raise HTTPException(status_code=422, detail="depth must be 'quick' or 'deep'.")

    # Phase 3: logged-in + personalize → snapshot holdings/preferences into the
    # run so the Portfolio Manager Agent can produce fit claims. Anonymous
    # requests behave exactly as in Phase 2.
    portfolio_context = None
    personalized = False
    if user is not None and req.personalize:
        portfolio_context = load_portfolio_context(db, user).model_dump()
        personalized = True

    run_id = runs.start(ticker, depth, req.lens, portfolio_context)
    return {"run_id": run_id, "ticker": ticker, "personalized": personalized}


@app.get("/research/{run_id}/events")
def research_events(run_id: str) -> StreamingResponse:
    if runs.get(run_id) is None:
        raise HTTPException(status_code=404, detail="Unknown run id.")
    return StreamingResponse(
        runs.sse_events(run_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/research/{run_id}/answer")
def research_answer(run_id: str, req: AnswerRequest) -> dict:
    run = runs.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Unknown run id.")
    if not runs.answer(run_id, req.answer.strip()):
        raise HTTPException(
            status_code=409, detail="Run is not waiting for an answer."
        )
    return {"ok": True}


@app.get("/research/{run_id}")
def research_status(run_id: str) -> dict:
    """Poll fallback: current status (and report once done)."""
    run = runs.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Unknown run id.")
    return {
        "run_id": run.run_id,
        "ticker": run.ticker,
        "status": run.status,
        "question": run.question,
        "report": run.report.model_dump() if run.report else None,
        "error": run.error,
    }
