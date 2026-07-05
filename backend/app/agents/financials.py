"""Financial Statement Agent — operating statistics from SEC EDGAR.

Claims are derived deterministically from filed 10-K figures, so confidence
is high (0.9+) and no LLM call is needed.

Methodology follows the operating-statistics conventions in Anthropic's
financial-services `comps-analysis` skill: revenue + growth, the full margin
stack (gross → operating → net), free cash flow (OCF − capex) with FCF
margin, and leverage. Includes the skill's margin-hierarchy sanity check
(gross ≥ operating ≥ net must hold by definition; a violation signals a
data-extraction problem and is surfaced as a flag, not silently reported).
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

        claims += self._revenue_claims(ticker, fin, fy, src, flags)
        claims += self._margin_claims(ticker, fin, src, flags)
        claims += self._cash_flow_claims(ticker, fin, src)
        claims += self._balance_sheet_claims(ticker, fin, src, flags)

        if not claims:
            flags.append("no_financial_claims")
        return AgentReport(agent=AGENT_ID, claims=claims, flags=flags)

    # -- growth --------------------------------------------------------------
    @staticmethod
    def _revenue_claims(ticker, fin, fy, src, flags) -> list[Claim]:
        claims: list[Claim] = []
        if fin.revenue is None:
            flags.append("missing_revenue")
            return claims
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
        if fin.net_income is not None and fin.net_income_prior:
            chg = (fin.net_income - fin.net_income_prior) / abs(fin.net_income_prior)
            claims.append(Claim(
                claim=f"{ticker} net income {'rose' if chg >= 0 else 'fell'} "
                      f"{abs(chg):.1%} year over year "
                      f"({_fmt_money(fin.net_income_prior)} → "
                      f"{_fmt_money(fin.net_income)}).",
                evidence=f"net_income={fin.net_income:,.0f} vs prior "
                         f"{fin.net_income_prior:,.0f} USD",
                source=src, confidence=0.95,
            ))
        return claims

    # -- margin stack (gross → operating → net) ------------------------------
    @staticmethod
    def _margin_claims(ticker, fin, src, flags) -> list[Claim]:
        claims: list[Claim] = []
        rev = fin.revenue
        if not rev:
            if fin.net_income is not None:
                claims.append(Claim(
                    claim=f"{ticker} reported net income of "
                          f"{_fmt_money(fin.net_income)}.",
                    evidence=f"net_income={fin.net_income:,.0f} USD",
                    source=src, confidence=0.9,
                ))
            return claims

        gross_m = fin.gross_profit / rev if fin.gross_profit is not None else None
        op_m = fin.operating_income / rev if fin.operating_income is not None else None
        net_m = fin.net_income / rev if fin.net_income is not None else None

        if gross_m is not None:
            claims.append(Claim(
                claim=f"{ticker} gross margin was {gross_m:.1%} "
                      f"(gross profit {_fmt_money(fin.gross_profit)}).",
                evidence=f"gross_profit={fin.gross_profit:,.0f} / revenue={rev:,.0f}",
                source=src, confidence=0.9,
            ))
        if op_m is not None:
            claims.append(Claim(
                claim=f"{ticker} operating margin was {op_m:.1%} "
                      f"(operating income {_fmt_money(fin.operating_income)}).",
                evidence=f"operating_income={fin.operating_income:,.0f} / "
                         f"revenue={rev:,.0f}",
                source=src, confidence=0.9,
            ))
        if net_m is not None:
            claims.append(Claim(
                claim=f"{ticker} net margin was {net_m:.1%} "
                      f"(net income {_fmt_money(fin.net_income)}).",
                evidence=f"net_income={fin.net_income:,.0f} / revenue={rev:,.0f}",
                source=src, confidence=0.9,
            ))

        # Sanity check from the comps-analysis skill: by definition
        # gross margin ≥ operating margin ≥ net margin. A violation usually
        # means an XBRL extraction issue — flag it rather than report quietly.
        stack = [m for m in (gross_m, op_m, net_m) if m is not None]
        if len(stack) >= 2 and any(
            stack[i] < stack[i + 1] - 1e-9 for i in range(len(stack) - 1)
        ):
            flags.append("margin_hierarchy_check_failed")
        return claims

    # -- cash generation -------------------------------------------------------
    @staticmethod
    def _cash_flow_claims(ticker, fin, src) -> list[Claim]:
        fcf = fin.free_cash_flow
        if fcf is None:
            return []
        capex_note = (
            f"capex={fin.capex:,.0f}" if fin.capex is not None else "capex unreported"
        )
        claims = [Claim(
            claim=f"{ticker} generated {_fmt_money(fcf)} of free cash flow "
                  f"(operating cash flow minus capex).",
            evidence=f"ocf={fin.operating_cash_flow:,.0f} − ({capex_note}) "
                     f"= fcf={fcf:,.0f} USD",
            source=src, confidence=0.9,
        )]
        if fin.revenue:
            fcf_m = fcf / fin.revenue
            claims.append(Claim(
                claim=f"{ticker} FCF margin was {fcf_m:.1%} — "
                      f"{'strong' if fcf_m >= 0.15 else 'positive' if fcf_m > 0 else 'negative'} "
                      f"cash conversion.",
                evidence=f"fcf={fcf:,.0f} / revenue={fin.revenue:,.0f}",
                source=src, confidence=0.9,
            ))
        return claims

    # -- leverage ---------------------------------------------------------------
    @staticmethod
    def _balance_sheet_claims(ticker, fin, src, flags) -> list[Claim]:
        claims: list[Claim] = []
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

        if fin.total_debt is not None and fin.cash_and_equivalents is not None:
            net_debt = fin.total_debt - fin.cash_and_equivalents
            position = "net debt" if net_debt > 0 else "net cash"
            claims.append(Claim(
                claim=f"{ticker} holds a {position} position of "
                      f"{_fmt_money(abs(net_debt))} "
                      f"(debt {_fmt_money(fin.total_debt)} vs cash "
                      f"{_fmt_money(fin.cash_and_equivalents)}).",
                evidence=f"long_term_debt={fin.total_debt:,.0f} − "
                         f"cash={fin.cash_and_equivalents:,.0f} "
                         f"= {net_debt:,.0f} USD",
                source=src, confidence=0.85,
            ))
        return claims
