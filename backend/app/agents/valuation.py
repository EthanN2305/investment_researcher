"""Valuation Agent — multiples derived from market data plus (when available)
the Financial Statement Agent's EDGAR figures.

Runs in a second stage of the graph so it can consume the financials agent's
output from shared state; degrades to market-data-only ratios with a flag if
financials are unavailable.

Methodology follows the valuation-multiples conventions in Anthropic's
financial-services `comps-analysis` skill:
- Enterprise value (market cap + debt − cash) drives EV/Revenue, so leverage
  is priced in — not just equity value.
- Reasonableness bands (EV/Revenue ~0.5–20x, P/E ~10–50x) contextualize each
  multiple instead of reporting a bare number.
- Red-flag rules: companies with negative earnings are not valued on
  earnings multiples (revenue multiples are used instead, with a flag), and
  a P/E above 100x is flagged as an extreme multiple.
"""
from __future__ import annotations

from app.models import AgentReport, Claim, Financials, MarketData
from app.tools.base import MarketDataProvider

AGENT_ID = "valuation"

# Reasonableness bands from the comps-analysis skill's sanity checks.
EV_REV_LOW, EV_REV_HIGH = 0.5, 20.0
PE_LOW, PE_HIGH = 10.0, 50.0
PE_EXTREME = 100.0


def _band_note(value: float, low: float, high: float) -> str:
    if value < low:
        return "below the typical band — potentially discounted or distressed"
    if value > high:
        return "above the typical band — priced for high growth"
    return "within the typical band"


class ValuationAgent:
    def __init__(self, market: MarketDataProvider) -> None:
        self._market = market

    def run(self, ticker: str, financials: Financials | None = None) -> AgentReport:
        md: MarketData = self._market.get_market_data(ticker)
        claims: list[Claim] = []
        flags: list[str] = []

        if md.pe_ratio is not None:
            claims.append(Claim(
                claim=f"{ticker} trades at a trailing P/E of {md.pe_ratio:.1f} — "
                      f"{_band_note(md.pe_ratio, PE_LOW, PE_HIGH)} "
                      f"(typical range ~{PE_LOW:.0f}–{PE_HIGH:.0f}x).",
                evidence=f"trailing_pe={md.pe_ratio:.2f} at price {md.price}",
                source=md.source, confidence=0.85,
            ))
            if md.pe_ratio > PE_EXTREME:
                flags.append("extreme_earnings_multiple")

        if md.market_cap and financials and financials.revenue:
            claims += self._filing_multiples(ticker, md, financials, flags)
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

    # -- multiples built from filed figures -------------------------------------
    @staticmethod
    def _filing_multiples(
        ticker: str, md: MarketData, fin: Financials, flags: list[str]
    ) -> list[Claim]:
        claims: list[Claim] = []
        src = f"{md.source} + {fin.source}"
        mcap = md.market_cap

        # Enterprise value prices the whole capital structure (comps skill:
        # EV = market cap + net debt). Falls back to market cap with a note
        # when debt/cash figures are missing.
        if fin.total_debt is not None and fin.cash_and_equivalents is not None:
            ev = mcap + fin.total_debt - fin.cash_and_equivalents
            ev_rev = ev / fin.revenue
            claims.append(Claim(
                claim=f"{ticker} trades at ~{ev_rev:.1f}x EV/Revenue — "
                      f"{_band_note(ev_rev, EV_REV_LOW, EV_REV_HIGH)} "
                      f"(typical range ~{EV_REV_LOW}–{EV_REV_HIGH:.0f}x).",
                evidence=f"EV = market_cap {mcap:,.0f} + debt {fin.total_debt:,.0f} "
                         f"− cash {fin.cash_and_equivalents:,.0f} = {ev:,.0f}; "
                         f"EV/revenue = {ev:,.0f}/{fin.revenue:,.0f}",
                source=src, confidence=0.85,
            ))
        else:
            ps = mcap / fin.revenue
            claims.append(Claim(
                claim=f"{ticker} trades at ~{ps:.1f}x trailing annual revenue "
                      f"(P/S; EV unavailable without filed debt/cash figures).",
                evidence=f"market_cap={mcap:,.0f} / revenue={fin.revenue:,.0f}",
                source=src, confidence=0.8,
            ))

        # Earnings multiple — only meaningful for positive earnings
        # (comps skill red flag: never value loss-makers on earnings multiples).
        if fin.net_income and fin.net_income > 0:
            pe = mcap / fin.net_income
            claims.append(Claim(
                claim=f"{ticker} is valued at {pe:.1f}x last fiscal year's net "
                      f"income — {_band_note(pe, PE_LOW, PE_HIGH)}.",
                evidence=f"market_cap={mcap:,.0f} / "
                         f"net_income={fin.net_income:,.0f}",
                source=src, confidence=0.85,
            ))
            if pe > PE_EXTREME:
                flags.append("extreme_earnings_multiple")
        elif fin.net_income is not None and fin.net_income <= 0:
            claims.append(Claim(
                claim=f"{ticker} had negative net income last fiscal year, so "
                      f"earnings multiples are not meaningful; revenue "
                      f"multiples are the relevant yardstick.",
                evidence=f"net_income={fin.net_income:,.0f} USD ≤ 0",
                source=src, confidence=0.9,
            ))
            flags.append("negative_earnings_multiple_unusable")

        # FCF yield — cash-based cross-check on the earnings multiple.
        fcf = fin.free_cash_flow
        if fcf is not None and mcap:
            yld = fcf / mcap
            claims.append(Claim(
                claim=f"{ticker} offers a {yld:.1%} trailing FCF yield "
                      f"({'cash-generative' if yld > 0 else 'cash-burning'} "
                      f"relative to its market value).",
                evidence=f"fcf={fcf:,.0f} / market_cap={mcap:,.0f}",
                source=src, confidence=0.85,
            ))
        return claims
