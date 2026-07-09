"""Tool interfaces (Protocols).

Depending on these abstractions rather than concrete providers is what lets
Phase 2+ swap Yahoo Finance for Polygon, NewsAPI for Benzinga, etc., without
changing the pipeline or report logic.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.models import (
    AgentReport,
    Claim,
    Financials,
    MarketData,
    NewsItem,
    PriceHistory,
    Recommendation,
)


class ToolError(Exception):
    """Raised by a tool when it cannot fulfil a request.

    The pipeline catches these and turns them into report `flags` rather than
    failing the whole request — a core Phase 1 guardrail.
    """


class RateLimitError(ToolError):
    """Raised when an upstream provider throttles us (e.g. Yahoo HTTP 429).

    Distinct from a generic ToolError so the API can return 503 (try again
    later) instead of 404 (ticker not found).
    """


class ToolTimeoutError(ToolError):
    """Raised when an outbound call exceeds its timeout budget (Phase 1.4).

    Distinct from a generic ToolError so the graph can surface an
    `<agent>_timeout` flag — telling the reader *why* coverage is missing —
    rather than a generic `<agent>_unavailable`.
    """


@runtime_checkable
class MarketDataProvider(Protocol):
    name: str

    def get_market_data(self, ticker: str) -> MarketData:
        """Return live-ish price/fundamentals for a ticker or raise ToolError."""
        ...


@runtime_checkable
class NewsProvider(Protocol):
    name: str

    def get_news(self, ticker: str, limit: int = 8) -> list[NewsItem]:
        """Return recent news items for a ticker or raise ToolError."""
        ...


@runtime_checkable
class LLMProvider(Protocol):
    name: str

    def generate_claims(
        self, ticker: str, market: MarketData, news: list[NewsItem]
    ) -> tuple[list[Claim], str]:
        """Return (claims, summary) grounded in the supplied evidence."""
        ...


# --- Phase 2 protocols --------------------------------------------------------


@runtime_checkable
class FinancialsProvider(Protocol):
    name: str

    def get_financials(self, ticker: str) -> Financials:
        """Return annual fundamentals for a ticker or raise ToolError."""
        ...


@runtime_checkable
class PriceHistoryProvider(Protocol):
    name: str

    def get_history(self, ticker: str, period: str = "1y") -> PriceHistory:
        """Return daily closes for a ticker or raise ToolError."""
        ...


@runtime_checkable
class AgentLLMProvider(Protocol):
    """LLM calls used by Phase 2 agents. Both return structured output only."""

    name: str

    def claims_from_news(self, ticker: str, news: list[NewsItem]) -> list[Claim]:
        """Turn news items into sourced claims about catalysts/risks."""
        ...

    def recommend(
        self,
        ticker: str,
        agent_reports: list[AgentReport],
        lens: str | None,
        flags: list[str],
    ) -> Recommendation:
        """Synthesize a recommendation from structured claims only."""
        ...

    def suggest_peers(
        self, ticker: str, sector: str | None, industry: str | None
    ) -> list[str]:
        """Name 3-5 comparable public-company tickers (judgment only — the
        Peer Comparison Agent fetches all numbers itself). Optional: agents
        probe with getattr() so providers without it degrade to a flag."""
        ...
