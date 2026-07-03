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


# --- Phase 2: multi-agent report contract ------------------------------------


class AgentReport(BaseModel):
    """Structured output of one specialist agent. Same Claim contract as Phase 1."""

    agent: str = Field(..., description="Agent id, e.g. 'news', 'financials'.")
    claims: list[Claim] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    status: str = Field(
        "ok", description="'ok' | 'failed' | 'skipped' — failures never crash a run."
    )


class Recommendation(BaseModel):
    """Recommendation Agent synthesis — built ONLY from structured claims."""

    summary: str = ""
    stance: str = Field("neutral", description="'bullish' | 'neutral' | 'bearish'.")
    confidence: float = Field(0.5, ge=0.0, le=1.0)


class FinalReport(BaseModel):
    """Phase 2 report: per-agent claim groups plus the recommendation synthesis."""

    ticker: str
    depth: str = "deep"
    lens: str | None = None
    agent_reports: list[AgentReport] = Field(default_factory=list)
    recommendation: Recommendation = Field(default_factory=Recommendation)
    flags: list[str] = Field(default_factory=list)
    generated_at: str = Field(..., description="ISO 8601 UTC timestamp.")
    disclaimer: str = (
        "This is an informational research tool, not investment advice. "
        "Verify all figures against primary sources before acting."
    )


# --- Intermediate tool payloads (internal; not the API response) ------------


class Financials(BaseModel):
    """Annual fundamentals extracted from SEC EDGAR companyfacts (XBRL)."""

    ticker: str
    cik: str | None = None
    company: str | None = None
    fiscal_year_end: str | None = None  # e.g. "2025-09-27"
    revenue: float | None = None
    revenue_prior: float | None = None
    net_income: float | None = None
    total_debt: float | None = None
    stockholders_equity: float | None = None
    source: str = "SEC EDGAR companyfacts"


class PriceHistory(BaseModel):
    """Daily closes (oldest → newest) for technical analysis."""

    ticker: str
    dates: list[str] = Field(default_factory=list)
    closes: list[float] = Field(default_factory=list)
    source: str = "Yahoo Finance (yfinance)"


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
