"""Portfolio Manager Agent — how does this ticker fit *your* portfolio?

Deterministic (like Valuation/Technicals): claims are derived from the user's
stored holdings and stated preferences plus the researched ticker's market
data. Same Claim/evidence/source/confidence contract as every other agent, so
the Recommendation Agent can weigh personalization against the general
analysis without special-casing.

Portfolio weights use cost value (quantity × per-share cost basis) — fully
reproducible from stored data, no N live price lookups per run. Evidence
strings say so explicitly.
"""
from __future__ import annotations

from app.models import AgentReport, Claim, MarketData, PortfolioContext
from app.tools.base import MarketDataProvider, ToolError

AGENT_ID = "portfolio"
_SOURCE = "User portfolio & stated preferences"

# Heuristic thresholds — deliberately simple and documented in the evidence.
CONCENTRATION_PCT = 0.20  # single position above this = concentration risk
SECTOR_OVERLAP_PCT = 0.30  # sector share above this = overlap warning
HIGH_PE = 35.0  # trailing P/E above this reads as growth-priced


class PortfolioManagerAgent:
    def __init__(self, market: MarketDataProvider) -> None:
        self._market = market

    def run(self, ticker: str, context: PortfolioContext) -> AgentReport:
        claims: list[Claim] = []
        flags: list[str] = []

        md: MarketData | None
        try:
            md = self._market.get_market_data(ticker)
        except ToolError:
            md = None
            flags.append("portfolio_no_market_data")

        holdings = context.holdings
        prefs = context.preferences

        if not holdings:
            flags.append("empty_portfolio")
        else:
            claims += self._position_claims(ticker, holdings)
            claims += self._sector_claims(ticker, holdings, md)

        if prefs is not None:
            claims += self._preference_claims(ticker, md, prefs)
        else:
            flags.append("no_stated_preferences")

        if not claims:
            flags.append("no_portfolio_claims")
        return AgentReport(agent=AGENT_ID, claims=claims, flags=flags)

    # -- holdings-based claims -------------------------------------------------
    @staticmethod
    def _position_claims(ticker: str, holdings) -> list[Claim]:
        total = sum(h.quantity * h.cost_basis for h in holdings)
        held = next((h for h in holdings if h.ticker == ticker), None)
        claims: list[Claim] = []

        if held is None:
            claims.append(Claim(
                claim=f"{ticker} would be a new position — you do not currently "
                      f"hold it among your {len(holdings)} holdings.",
                evidence=f"holdings={[h.ticker for h in holdings]}",
                source=_SOURCE, confidence=1.0,
            ))
            return claims

        weight = (held.quantity * held.cost_basis) / total if total else 0.0
        claims.append(Claim(
            claim=f"You already hold {ticker}: {held.quantity:g} shares at a "
                  f"${held.cost_basis:,.2f} cost basis "
                  f"(~{weight:.0%} of portfolio by cost value).",
            evidence=f"{held.quantity:g} × ${held.cost_basis:,.2f} = "
                     f"${held.quantity * held.cost_basis:,.2f} of "
                     f"${total:,.2f} total cost value",
            source=_SOURCE, confidence=1.0,
        ))
        if weight >= CONCENTRATION_PCT:
            claims.append(Claim(
                claim=f"Concentration risk: {ticker} is already ~{weight:.0%} of "
                      f"your portfolio (threshold {CONCENTRATION_PCT:.0%}); adding "
                      f"more increases single-name exposure.",
                evidence=f"position weight {weight:.1%} ≥ {CONCENTRATION_PCT:.0%} "
                         "by cost value",
                source=_SOURCE, confidence=0.9,
            ))
        return claims

    @staticmethod
    def _sector_claims(ticker: str, holdings, md: MarketData | None) -> list[Claim]:
        sector = md.sector if md else None
        if not sector:
            return []
        total = sum(h.quantity * h.cost_basis for h in holdings)
        if not total:
            return []
        same = [h for h in holdings if h.sector == sector and h.ticker != ticker]
        share = sum(h.quantity * h.cost_basis for h in same) / total
        if not same:
            return [Claim(
                claim=f"{ticker} ({sector}) would diversify you into a sector "
                      f"where you currently hold nothing.",
                evidence=f"no existing holdings tagged '{sector}'",
                source=_SOURCE, confidence=0.8,
            )]
        claims = [Claim(
            claim=f"Sector overlap: {ticker} is in {sector}, where you already "
                  f"hold {', '.join(h.ticker for h in same)} "
                  f"(~{share:.0%} of portfolio by cost value).",
            evidence=f"{sector} exposure {share:.1%} across {len(same)} "
                     "existing positions",
            source=_SOURCE, confidence=0.85,
        )]
        if share >= SECTOR_OVERLAP_PCT:
            claims.append(Claim(
                claim=f"Adding {ticker} would push your already-heavy {sector} "
                      f"exposure (~{share:.0%}) higher "
                      f"(threshold {SECTOR_OVERLAP_PCT:.0%}).",
                evidence=f"sector share {share:.1%} ≥ {SECTOR_OVERLAP_PCT:.0%}",
                source=_SOURCE, confidence=0.85,
            ))
        return claims

    # -- preference-based claims -------------------------------------------------
    @staticmethod
    def _preference_claims(ticker: str, md: MarketData | None, prefs) -> list[Claim]:
        claims: list[Claim] = []
        pe = md.pe_ratio if md else None
        sector = md.sector if md else None

        # Growth/value lean vs valuation multiple.
        if prefs.growth_value_lean == "value" and pe is not None and pe >= HIGH_PE:
            claims.append(Claim(
                claim=f"Possible mismatch with your stated value lean: {ticker} "
                      f"trades at a trailing P/E of {pe:.1f} "
                      f"(≥ {HIGH_PE:.0f} reads as growth-priced).",
                evidence=f"stated lean='value'; trailing_pe={pe:.2f}",
                source=_SOURCE, confidence=0.75,
            ))
        elif prefs.growth_value_lean == "growth" and pe is not None and pe < 15:
            claims.append(Claim(
                claim=f"{ticker}'s trailing P/E of {pe:.1f} is value-territory "
                      f"pricing, which may not match your stated growth lean.",
                evidence=f"stated lean='growth'; trailing_pe={pe:.2f}",
                source=_SOURCE, confidence=0.6,
            ))

        # Risk tolerance vs price position in 52-week range (rough proxy).
        if (
            prefs.risk_tolerance == "low"
            and md is not None
            and md.price and md.fifty_two_week_high and md.fifty_two_week_low
        ):
            span = md.fifty_two_week_high - md.fifty_two_week_low
            vol_proxy = span / md.price if md.price else 0.0
            if vol_proxy >= 0.5:
                claims.append(Claim(
                    claim=f"{ticker}'s 52-week range spans ~{vol_proxy:.0%} of its "
                          f"current price — a wide range for a stated low risk "
                          f"tolerance.",
                    evidence=f"range {md.fifty_two_week_low:.2f}–"
                             f"{md.fifty_two_week_high:.2f} vs price {md.price:.2f}; "
                             "stated risk_tolerance='low'",
                    source=_SOURCE, confidence=0.65,
                ))

        # Stated sector interests.
        if sector and prefs.sector_interests:
            interested = any(
                s.lower() in sector.lower() or sector.lower() in s.lower()
                for s in prefs.sector_interests
            )
            if interested:
                claims.append(Claim(
                    claim=f"{ticker} matches your stated sector interests "
                          f"({sector}).",
                    evidence=f"stated interests={prefs.sector_interests}; "
                             f"ticker sector='{sector}'",
                    source=_SOURCE, confidence=0.9,
                ))

        # Time horizon note (informational, low stakes).
        if prefs.time_horizon == "short":
            claims.append(Claim(
                claim="Your stated time horizon is short — single-stock research "
                      "conclusions here are long-horizon by nature; weigh "
                      "near-term claims (technicals, news) more heavily.",
                evidence="stated time_horizon='short'",
                source=_SOURCE, confidence=0.7,
            ))
        return claims
