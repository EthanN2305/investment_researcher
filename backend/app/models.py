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
    # Phase 4: overall confidence is *derived* (reasoned over the underlying
    # agents' confidence levels), not just the LLM's self-estimate. These
    # fields surface the derivation in the UI.
    agent_confidences: dict[str, float] = Field(
        default_factory=dict,
        description="Mean claim confidence per contributing agent, 0-1.",
    )
    confidence_rationale: str = Field(
        "", description="Human-readable explanation of the derived confidence."
    )


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
    net_income_prior: float | None = None
    gross_profit: float | None = None
    operating_income: float | None = None
    operating_cash_flow: float | None = None
    capex: float | None = None
    cash_and_equivalents: float | None = None
    total_debt: float | None = None
    stockholders_equity: float | None = None
    source: str = "SEC EDGAR companyfacts"

    @property
    def free_cash_flow(self) -> float | None:
        """FCF = operating cash flow − capex (comps-analysis convention)."""
        if self.operating_cash_flow is None:
            return None
        return self.operating_cash_flow - (self.capex or 0.0)


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


# --- Phase 3: accounts, portfolios, preferences -------------------------------

RISK_TOLERANCES = ("low", "medium", "high")
LEANS = ("growth", "value", "balanced")
HORIZONS = ("short", "medium", "long")


class SignupRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=255, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    password: str = Field(..., min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    email: str


class HoldingIn(BaseModel):
    """Create/update payload for one position."""

    ticker: str = Field(..., min_length=1, max_length=12)
    quantity: float = Field(..., gt=0)
    cost_basis: float = Field(..., ge=0, description="Per-share cost basis.")


class HoldingOut(HoldingIn):
    id: int
    sector: str | None = None


class PreferencesIn(BaseModel):
    """Explicitly stated preferences (Phase 3 uses nothing inferred)."""

    risk_tolerance: str | None = Field(None, description="'low'|'medium'|'high'")
    sector_interests: list[str] = Field(default_factory=list)
    growth_value_lean: str | None = Field(None, description="'growth'|'value'|'balanced'")
    time_horizon: str | None = Field(None, description="'short'|'medium'|'long'")


class PreferencesOut(PreferencesIn):
    pass


class PortfolioContext(BaseModel):
    """Snapshot of a user's holdings + preferences, passed into the graph so
    the Portfolio Manager Agent never touches the DB directly."""

    user_email: str
    holdings: list[HoldingOut] = Field(default_factory=list)
    preferences: PreferencesOut | None = None


# --- Phase 4: watchlists, summaries, alerts, notifications --------------------

ALERT_CONDITIONS = ("price_move", "high_confidence_claim", "negative_news")

# Default thresholds when the user doesn't set one.
ALERT_DEFAULT_THRESHOLDS = {
    "price_move": 5.0,             # abs % daily move
    "high_confidence_claim": 0.85,  # claim confidence 0-1
    "negative_news": None,          # no threshold — keyword-based
}


class WatchlistItemIn(BaseModel):
    ticker: str = Field(..., min_length=1, max_length=12)
    note: str | None = Field(None, max_length=255)


class WatchlistItemOut(WatchlistItemIn):
    id: int
    created_at: str = ""


class StoredReportSummary(BaseModel):
    """Feed item — everything the dashboard needs without the full report."""

    id: int
    ticker: str
    stance: str
    confidence: float
    summary: str
    trigger: str
    created_at: str


class StoredReportOut(StoredReportSummary):
    report: FinalReport


class AlertRuleIn(BaseModel):
    ticker: str = Field(..., min_length=1, max_length=12)
    condition: str = Field(..., description=f"One of {ALERT_CONDITIONS}")
    threshold: float | None = Field(
        None,
        description="price_move: abs %% daily move; "
        "high_confidence_claim: min confidence 0-1; negative_news: unused.",
    )
    email: bool = False
    active: bool = True


class AlertRuleOut(AlertRuleIn):
    id: int


DIGEST_FREQUENCIES = ("daily", "weekly", "monthly")


class DigestPreferenceIn(BaseModel):
    """Email digest settings: how often the daily feed gets emailed."""

    enabled: bool = False
    frequency: str = Field(
        "daily", description="'daily' | 'weekly' | 'monthly' (1st of the month)"
    )
    weekday: int | None = Field(
        None, ge=0, le=6,
        description="Weekly only: 0=Monday … 6=Sunday. Ignored otherwise.",
    )


class DigestPreferenceOut(DigestPreferenceIn):
    last_sent_at: str | None = None


class NotificationOut(BaseModel):
    id: int
    ticker: str
    condition: str
    title: str
    body: str
    report_id: int | None = None
    read: bool
    created_at: str
