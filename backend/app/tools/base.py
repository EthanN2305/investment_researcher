"""Tool interfaces (Protocols).

Depending on these abstractions rather than concrete providers is what lets
Phase 2+ swap Yahoo Finance for Polygon, NewsAPI for Benzinga, etc., without
changing the pipeline or report logic.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.models import Claim, MarketData, NewsItem


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
