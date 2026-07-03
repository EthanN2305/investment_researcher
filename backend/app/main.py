"""FastAPI app for Phase 1 — single-ticker research report.

Stateless per request. POST /research/{ticker} runs the pipeline and returns a
structured ResearchReport. Tools are constructed lazily so the app still boots
(and /health works) even if API keys are missing.
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.logstore import log_report
from app.models import ResearchReport
from app.pipeline import ResearchPipeline
from app.tools import AnthropicLLM, NewsAPINews, YFinanceMarketData
from app.tools.base import ToolError

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("api")

app = FastAPI(
    title="AI Investment Research Analyst — Phase 1",
    version="0.1.0",
    description="Enter a ticker, get a sourced, confidence-scored research report.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_methods=["*"],
    allow_headers=["*"],
)


def build_pipeline() -> ResearchPipeline:
    """Construct the pipeline with default providers.

    Swap providers here (or via DI in tests) without touching report logic.
    """
    return ResearchPipeline(
        market=YFinanceMarketData(),
        news=NewsAPINews(),
        llm=AnthropicLLM(),
    )


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "anthropic_key_set": bool(settings.anthropic_api_key),
        "newsapi_key_set": bool(settings.newsapi_key),
    }


@app.post("/research/{ticker}", response_model=ResearchReport)
def research(ticker: str) -> ResearchReport:
    ticker = ticker.strip().upper()
    if not ticker or len(ticker) > 12:
        raise HTTPException(status_code=422, detail="Invalid ticker symbol.")

    try:
        pipeline = build_pipeline()
    except ToolError as exc:
        # Missing/invalid API keys surface here.
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    try:
        report = pipeline.run(ticker)
    except ToolError as exc:
        # e.g. unknown ticker, market data unavailable.
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("unexpected pipeline error for %s", ticker)
        raise HTTPException(
            status_code=500, detail=f"Unexpected error generating report: {exc}"
        ) from exc

    log_report(report)
    return report
