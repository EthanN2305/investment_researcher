"""Technical Analysis Agent — trend, momentum, and risk from price history.

Pure arithmetic over daily closes (no LLM, no pandas required): SMA-50/200,
14-day Wilder RSI, a 3-month trend reading, plus two risk statistics drawn
from institutional research conventions (Anthropic financial-services
skills): annualized realized volatility and maximum drawdown. The risk
claims give the Portfolio Manager Agent a real volatility measure to match
against stated risk tolerance instead of a 52-week-range proxy.
"""
from __future__ import annotations

from app.models import AgentReport, Claim, PriceHistory
from app.tools.base import PriceHistoryProvider

AGENT_ID = "technicals"


def sma(values: list[float], window: int) -> float | None:
    if len(values) < window:
        return None
    return sum(values[-window:]) / window


def rsi(values: list[float], period: int = 14) -> float | None:
    """Wilder-smoothed RSI over the full series."""
    if len(values) < period + 1:
        return None
    deltas = [values[i] - values[i - 1] for i in range(1, len(values))]
    gains = [max(d, 0.0) for d in deltas]
    losses = [max(-d, 0.0) for d in deltas]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for g, l in zip(gains[period:], losses[period:]):
        avg_gain = (avg_gain * (period - 1) + g) / period
        avg_loss = (avg_loss * (period - 1) + l) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)


def annualized_volatility(values: list[float]) -> float | None:
    """Std-dev of daily returns × √252, over the full series."""
    if len(values) < 21:  # need at least ~a month of data
        return None
    rets = [
        (values[i] - values[i - 1]) / values[i - 1]
        for i in range(1, len(values))
        if values[i - 1]
    ]
    if len(rets) < 2:
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    return (var ** 0.5) * (252 ** 0.5)


def max_drawdown(values: list[float]) -> float | None:
    """Largest peak-to-trough decline over the series (positive fraction)."""
    if len(values) < 2:
        return None
    peak, worst = values[0], 0.0
    for v in values[1:]:
        peak = max(peak, v)
        if peak:
            worst = max(worst, (peak - v) / peak)
    return worst


class TechnicalAnalysisAgent:
    def __init__(self, prices: PriceHistoryProvider) -> None:
        self._prices = prices

    def run(self, ticker: str) -> AgentReport:
        hist: PriceHistory = self._prices.get_history(ticker, period="1y")
        closes = hist.closes
        claims: list[Claim] = []
        flags: list[str] = []
        src = hist.source
        last = closes[-1]

        sma50, sma200 = sma(closes, 50), sma(closes, 200)
        if sma50 is not None:
            rel = "above" if last > sma50 else "below"
            claims.append(Claim(
                claim=f"{ticker} trades {rel} its 50-day moving average "
                      f"({last:.2f} vs {sma50:.2f}).",
                evidence=f"close={last:.2f}, sma50={sma50:.2f}",
                source=src, confidence=0.9,
            ))
        if sma50 is not None and sma200 is not None:
            regime = "golden-cross (bullish)" if sma50 > sma200 else \
                     "death-cross (bearish)"
            claims.append(Claim(
                claim=f"{ticker}'s 50-day average is "
                      f"{'above' if sma50 > sma200 else 'below'} its 200-day "
                      f"average — a {regime} configuration.",
                evidence=f"sma50={sma50:.2f}, sma200={sma200:.2f}",
                source=src, confidence=0.85,
            ))
        elif sma200 is None:
            flags.append("insufficient_history_for_sma200")

        r = rsi(closes)
        if r is not None:
            zone = "overbought" if r >= 70 else "oversold" if r <= 30 else "neutral"
            claims.append(Claim(
                claim=f"{ticker}'s 14-day RSI is {r:.0f} ({zone}).",
                evidence=f"rsi14={r:.1f} from {len(closes)} daily closes",
                source=src, confidence=0.9,
            ))

        if len(closes) >= 63:  # ~3 trading months
            chg = (last - closes[-63]) / closes[-63]
            claims.append(Claim(
                claim=f"{ticker} is {'up' if chg >= 0 else 'down'} {abs(chg):.1%} "
                      f"over the past three months.",
                evidence=f"close={last:.2f} vs 63 sessions ago {closes[-63]:.2f}",
                source=src, confidence=0.9,
            ))

        vol = annualized_volatility(closes)
        if vol is not None:
            zone = "low" if vol < 0.20 else "moderate" if vol < 0.40 else "high"
            claims.append(Claim(
                claim=f"{ticker}'s annualized realized volatility is {vol:.0%} "
                      f"({zone} for a single stock).",
                evidence=f"stdev(daily returns) × √252 = {vol:.3f} over "
                         f"{len(closes)} closes",
                source=src, confidence=0.9,
            ))

        dd = max_drawdown(closes)
        if dd is not None and dd > 0:
            claims.append(Claim(
                claim=f"{ticker}'s largest peak-to-trough decline over the "
                      f"period was {dd:.1%}.",
                evidence=f"max drawdown={dd:.3f} across {len(closes)} closes",
                source=src, confidence=0.9,
            ))

        if not claims:
            flags.append("no_technical_claims")
        return AgentReport(agent=AGENT_ID, claims=claims, flags=flags)
