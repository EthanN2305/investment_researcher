"""Financial Statement Agent — revenue, margins, debt from SEC EDGAR.

Claims are derived deterministically from filed 10-K figures, so confidence
is high (0.9+) and no LLM call is needed.
"""
from __future__ import annotations

from app.models import AgentReport, Claim, Financials
from app.tools.base import FinancialsProvider

AGENT_ID = "financials"


def _fmt_money(v: float) -> str:
    for unit, div in (("T", 1e12), ("B", 1e9), ("M", 1e6)):
        if abs(v) >= div:
            return f"${v / div:.2f}{unit}"
    return f"${v:,.0f}"


class FinancialStatementAgent:
    def __init__(self, financials: FinancialsProvider) -> None:
        self._financials = financials

    def run(self, ticker: str) -> AgentReport:
        fin: Financials = self._financials.get_financials(ticker)
        claims: list[Claim] = []
        flags: list[str] = []
        src = fin.source
        fy = fin.fiscal_year_end or "latest fiscal year"

        if fin.revenue is not None:
            claims.append(Claim(
                claim=f"{ticker} reported revenue of {_fmt_money(fin.revenue)} "
                      f"for the fiscal year ending {fy}.",
                evidence=f"revenue={fin.revenue:,.0f} USD (10-K, FY end {fy})",
                source=src, confidence=0.95,
            ))
            if fin.revenue_prior:
                growth = (fin.revenue - fin.revenue_prior) / abs(fin.revenue_prior)
                claims.append(Claim(
                    claim=f"{ticker} revenue {'grew' if growth >= 0 else 'declined'} "
                          f"{abs(growth):.1%} year over year.",
                    evidence=f"revenue={fin.revenue:,.0f} vs prior "
                             f"{fin.revenue_prior:,.0f} USD",
                    source=src, confidence=0.95,
                ))
        else:
            flags.append("missing_revenue")

        if fin.net_income is not None:
            if fin.revenue:
                margin = fin.net_income / fin.revenue
                claims.append(Claim(
                    claim=f"{ticker} net margin was {margin:.1%} "
                          f"(net income {_fmt_money(fin.net_income)}).",
                    evidence=f"net_income={fin.net_income:,.0f} / "
                             f"revenue={fin.revenue:,.0f}",
                    source=src, confidence=0.9,
                ))
            else:
                claims.append(Claim(
                    claim=f"{ticker} reported net income of "
                          f"{_fmt_money(fin.net_income)}.",
                    evidence=f"net_income={fin.net_income:,.0f} USD",
                    source=src, confidence=0.9,
                ))

        if fin.total_debt is not None and fin.stockholders_equity:
            de = fin.total_debt / fin.stockholders_equity
            claims.append(Claim(
                claim=f"{ticker} debt-to-equity ratio is {de:.2f} "
                      f"(long-term debt {_fmt_money(fin.total_debt)}).",
                evidence=f"long_term_debt={fin.total_debt:,.0f} / "
                         f"equity={fin.stockholders_equity:,.0f}",
                source=src, confidence=0.85,
            ))
        elif fin.total_debt is None:
            flags.append("missing_debt_data")

        if not claims:
            flags.append("no_financial_claims")
        return AgentReport(agent=AGENT_ID, claims=claims, flags=flags)
