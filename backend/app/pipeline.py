"""Phase 1 research pipeline.

One linear pipeline (not yet split into agents): fetch market data + news,
hand both to the LLM, assemble a structured ResearchReport. Tools are injected
so they can be swapped or mocked. Tool failures become `flags`, not crashes.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.models import MarketData, NewsItem, ResearchReport
from app.tools.base import LLMProvider, MarketDataProvider, NewsProvider, ToolError

logger = logging.getLogger("pipeline")


class ResearchPipeline:
    def __init__(
        self,
        market: MarketDataProvider,
        news: NewsProvider,
        llm: LLMProvider,
    ) -> None:
        self._market = market
        self._news = news
        self._llm = llm

    def run(self, ticker: str) -> ResearchReport:
        ticker = ticker.strip().upper()
        flags: list[str] = []

        # 1. Market data is required — if it fails, the request fails.
        market: MarketData = self._market.get_market_data(ticker)

        # 2. News is best-effort — degrade gracefully.
        news: list[NewsItem] = []
        try:
            news = self._news.get_news(ticker)
        except ToolError as exc:
            logger.warning("news tool failed for %s: %s", ticker, exc)
            flags.append("missing_news")
        if not news and "missing_news" not in flags:
            flags.append("no_recent_news")

        # 3. LLM synthesis is required.
        claims, summary = self._llm.generate_claims(ticker, market, news)
        if not claims:
            flags.append("no_claims_generated")

        return ResearchReport(
            ticker=ticker,
            claims=claims,
            summary=summary,
            flags=flags,
            generated_at=datetime.now(timezone.utc).isoformat(),
        )
