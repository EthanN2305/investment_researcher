"""Valuation Agent — P/E, P/S, price-vs-range, derived from market data plus
(when available) the Financial Statement Agent's EDGAR figures.

Runs in a second stage of the graph so it can consume the financials agent's
output from shared state; degrades to market-data-only ratios with a flag if
financials are unavailable.
"""
from __future__ import annotations

from app.models import AgentReport, Claim, Financials, MarketData
from app.tools.base import MarketDataProvider

AGENT_ID = "valuation"


class ValuationAgent:
    def __init__(self, market: MarketDataProvider) -> None:
        self._market = market

    def run(self, ticker: str, financials: Financials | None = None) -> AgentReport:
        md: MarketData = self._market.get_market_data(ticker)
        claims: list[Claim] = []
        flags: list[str] = []

        if md.pe_ratio is not None:
            claims.append(Claim(
                claim=f"{ticker} trades at a trailing P/E of {md.pe_ratio:.1f}.",
                evidence=f"trailing_pe={md.pe_ratio:.2f} at price {md.price}",
                source=md.source, confidence=0.85,
            ))

        if md.market_cap and financials and financials.revenue:
            ps = md.market_cap / financials.revenue
            claims.append(Claim(
                claim=f"{ticker} trades at ~{ps:.1f}x trailing annual revenue (P/S).",
                evidence=f"market_cap={md.market_cap:,.0f} / "
                         f"revenue={financials.revenue:,.0f}",
                source=f"{md.source} + {financials.source}", confidence=0.85,
            ))
            if financials.net_income and financials.net_income > 0:
                pe = md.market_cap / financials.net_income
                claims.append(Claim(
                    claim=f"{ticker} is valued at {pe:.1f}x last fiscal year's "
                          f"net income (earnings multiple from filings).",
                    evidence=f"market_cap={md.market_cap:,.0f} / "
                             f"net_income={financials.net_income:,.0f}",
                    source=f"{md.source} + {financials.source}", confidence=0.85,
                ))
        elif financials is None:
            flags.append("valuation_without_financials")

        if md.price and md.fifty_two_week_high and md.fifty_two_week_low:
            span = md.fifty_two_week_high - md.fifty_two_week_low
            pos = (md.price - md.fifty_two_week_low) / span if span else 0.5
            claims.append(Claim(
                claim=f"{ticker} trades at {pos:.0%} of its 52-week range "
                      f"({md.fifty_two_week_low:.2f}–{md.fifty_two_week_high:.2f}).",
                evidence=f"price={md.price:.2f}, low={md.fifty_two_week_low:.2f}, "
                         f"high={md.fifty_two_week_high:.2f}",
                source=md.source, confidence=0.9,
            ))

        if not claims:
            flags.append("no_valuation_claims")
        return AgentReport(agent=AGENT_ID, claims=claims, flags=flags)
