"""Shared data models.

The structured-output contract defined here is the backbone of the whole
project: every agent (there is only one in Phase 1) must speak `Claim` /
`ResearchReport` so later phases can compose claims without re-parsing prose.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class Claim(BaseModel):
    """A single, sourced, confidence-scored assertion about a ticker."""

    claim: str = Field(..., description="The assertion, e.g. 'Revenue grew 12% YoY'.")
    evidence: str = Field(..., description="The concrete data backing the claim.")
    source: str = Field(..., description="URL or filing/source name for the evidence.")
    confidence: float = Field(
        ..., ge=0.0, le=1.0, description="Model confidence in the claim, 0-1."
    )


class ResearchReport(BaseModel):
    """The Phase 1 report contract returned by POST /research/{ticker}."""

    ticker: str
    claims: list[Claim] = Field(default_factory=list)
    summary: str = ""
    flags: list[str] = Field(
        default_factory=list,
        description="Data-quality warnings, e.g. 'missing_news', 'stale_price'.",
    )
    generated_at: str = Field(..., description="ISO 8601 UTC timestamp.")
    disclaimer: str = (
        "This is an informational research tool, not investment advice. "
        "Verify all figures against primary sources before acting."
    )


# --- Intermediate tool payloads (internal; not the API response) ------------


class MarketData(BaseModel):
    ticker: str
    name: str | None = None
    price: float | None = None
    currency: str | None = None
    market_cap: float | None = None
    volume: float | None = None
    pe_ratio: float | None = None
    fifty_two_week_high: float | None = None
    fifty_two_week_low: float | None = None
    sector: str | None = None
    industry: str | None = None
    as_of: str | None = None
    source: str = "Yahoo Finance (yfinance)"


class NewsItem(BaseModel):
    title: str
    url: str
    source: str | None = None
    published_at: str | None = None
    summary: str | None = None
