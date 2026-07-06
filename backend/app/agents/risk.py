"""Market Risk Agent — how does this stock move relative to the market?

Complements the Technical Analysis Agent's standalone risk statistics
(volatility, drawdown) with *market-relative* measures used across
Anthropic's financial-services wealth-management skills (client reviews and
comps sheets both report beta): beta, correlation, and relative volatility
versus a broad-market benchmark.

Fully deterministic — two price-history fetches and covariance arithmetic,
no LLM. Series are aligned by trading date before computing returns, so a
ticker with missing sessions doesn't skew the numbers. The Portfolio Manager
and Recommendation agents can weigh a 1.8-beta name very differently for a
low-risk-tolerance user than a 0.6-beta one.
"""
from __future__ import annotations

from app.models import AgentReport, Claim, PriceHistory
from app.tools.base import PriceHistoryProvider, ToolError

AGENT_ID = "risk"

BENCHMARK = "SPY"  # S&P 500 proxy ETF
MIN_OVERLAP = 60   # aligned sessions needed for a meaningful beta


def _aligned_returns(
    a: PriceHistory, b: PriceHistory
) -> tuple[list[float], list[float]]:
    """Daily returns for the dates both series share (oldest → newest)."""
    a_map = dict(zip(a.dates, a.closes))
    b_map = dict(zip(b.dates, b.closes))
    common = sorted(set(a_map) & set(b_map))
    ra, rb = [], []
    for prev, cur in zip(common, common[1:]):
        pa, pb = a_map[prev], b_map[prev]
        if pa and pb:
            ra.append((a_map[cur] - pa) / pa)
            rb.append((b_map[cur] - pb) / pb)
    return ra, rb


def beta_and_correlation(
    ra: list[float], rb: list[float]
) -> tuple[float, float] | None:
    """(beta, correlation) of a vs benchmark b, or None if degenerate."""
    n = len(ra)
    if n < 2:
        return None
    ma, mb = sum(ra) / n, sum(rb) / n
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb)) / (n - 1)
    var_b = sum((y - mb) ** 2 for y in rb) / (n - 1)
    var_a = sum((x - ma) ** 2 for x in ra) / (n - 1)
    if var_b <= 0 or var_a <= 0:
        return None
    beta = cov / var_b
    corr = cov / ((var_a ** 0.5) * (var_b ** 0.5))
    return beta, corr


class MarketRiskAgent:
    def __init__(self, prices: PriceHistoryProvider) -> None:
        self._prices = prices

    def run(self, ticker: str) -> AgentReport:
        claims: list[Claim] = []
        flags: list[str] = []

        hist = self._prices.get_history(ticker, period="1y")
        try:
            bench = self._prices.get_history(BENCHMARK, period="1y")
        except ToolError:
            return AgentReport(agent=AGENT_ID, flags=["risk_no_benchmark_data"])
        src = f"{hist.source} ({ticker} vs {BENCHMARK})"

        ra, rb = _aligned_returns(hist, bench)
        if len(ra) < MIN_OVERLAP:
            return AgentReport(
                agent=AGENT_ID, flags=["risk_insufficient_overlap"]
            )

        stats = beta_and_correlation(ra, rb)
        if stats is None:
            return AgentReport(agent=AGENT_ID, flags=["risk_degenerate_series"])
        beta, corr = stats

        zone = (
            "defensive (moves less than the market)" if beta < 0.8
            else "market-like" if beta <= 1.2
            else "aggressive (amplifies market moves)"
        )
        claims.append(Claim(
            claim=f"{ticker}'s one-year beta vs the S&P 500 is {beta:.2f} — "
                  f"{zone}.",
            evidence=f"beta={beta:.3f} from {len(ra)} aligned daily returns "
                     f"vs {BENCHMARK}",
            source=src, confidence=0.85,
        ))

        diversifier = (
            "offering meaningful diversification" if corr < 0.5
            else "moving largely with the broad market"
        )
        claims.append(Claim(
            claim=f"{ticker}'s daily returns are {corr:.0%} correlated with "
                  f"the S&P 500, {diversifier}.",
            evidence=f"correlation={corr:.3f} over {len(ra)} aligned sessions",
            source=src, confidence=0.85,
        ))

        n = len(ra)
        var_a = sum((x - sum(ra) / n) ** 2 for x in ra) / (n - 1)
        var_b = sum((y - sum(rb) / n) ** 2 for y in rb) / (n - 1)
        if var_b > 0:
            rel_vol = (var_a / var_b) ** 0.5
            claims.append(Claim(
                claim=f"{ticker} has been {rel_vol:.1f}x as volatile as the "
                      f"S&P 500 over the past year.",
                evidence=f"stdev ratio {ticker}/{BENCHMARK} = {rel_vol:.2f} "
                         f"(daily returns)",
                source=src, confidence=0.85,
            ))

        return AgentReport(agent=AGENT_ID, claims=claims, flags=flags)
