"""FastAPI app for Phase 2 — multi-agent research runs.

Flow:
  POST /research                  → start a run, returns {run_id}
  GET  /research/{run_id}/events  → SSE stream of per-agent progress,
                                    clarifying questions, and the final report
  POST /research/{run_id}/answer  → answer a clarifying question; the paused
                                    LangGraph run resumes from its checkpoint

Runs are in-memory (no persistence yet — Phase 3 adds accounts/storage).
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.config import settings
from app.graph import build_graph
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
    title="AI Investment Research Analyst — Phase 2",
    version="0.2.0",
    description=(
        "Multi-agent research: planner-orchestrated News, Financial Statement, "
        "Valuation, and Technical Analysis agents with a Recommendation synthesis."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Graph + run manager are process-wide singletons. The LLM provider is lenient
# about missing keys (agents fail soft with flags), so this always boots.
_graph = build_graph(
    market=YFinanceMarketData(),
    news=NewsAPINews(),
    financials=SecEdgarFinancials(),
    prices=YFinancePriceHistory(),
    llm=AnthropicAgentLLM(),
)
runs = RunManager(_graph)


class StartRequest(BaseModel):
    ticker: str = Field(..., min_length=1, max_length=12)
    depth: str | None = Field(None, description="'quick' | 'deep' | None (planner asks)")
    lens: str | None = Field(None, description="'growth' | 'value' | 'balanced'")


class AnswerRequest(BaseModel):
    answer: str = Field(..., min_length=1, max_length=200)


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "phase": 2,
        "anthropic_key_set": bool(settings.anthropic_api_key),
        "newsapi_key_set": bool(settings.newsapi_key),
    }


@app.post("/research")
def start_research(req: StartRequest) -> dict:
    ticker = req.ticker.strip().upper()
    if not ticker or not ticker.replace(".", "").replace("-", "").isalnum():
        raise HTTPException(status_code=422, detail="Invalid ticker symbol.")
    depth = req.depth.lower() if req.depth else None
    if depth is not None and depth not in ("quick", "deep"):
        raise HTTPException(status_code=422, detail="depth must be 'quick' or 'deep'.")
    run_id = runs.start(ticker, depth, req.lens)
    return {"run_id": run_id, "ticker": ticker}


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
