"""Daily price history via yfinance, for the Technical Analysis Agent.

Uses the light chart endpoint (`Ticker.history`), which is far less throttled
than quoteSummary. Swap target: Polygon, Alpha Vantage, Stooq.
"""
from __future__ import annotations

import logging

import yfinance as yf

from app.models import PriceHistory
from app.tools.base import RateLimitError, ToolError
from app.tools.market_data import _is_rate_limit, _make_session

logger = logging.getLogger("prices")


class YFinancePriceHistory:
    name = "yfinance-history"

    def get_history(self, ticker: str, period: str = "1y") -> PriceHistory:
        ticker = ticker.strip().upper()
        session = _make_session()
        try:
            t = yf.Ticker(ticker, session=session) if session else yf.Ticker(ticker)
        except TypeError:
            t = yf.Ticker(ticker)

        try:
            df = t.history(period=period, interval="1d", auto_adjust=True)
        except Exception as exc:  # noqa: BLE001
            if _is_rate_limit(exc):
                raise RateLimitError(str(exc)) from exc
            raise ToolError(f"Price history request failed: {exc}") from exc

        if df is None or df.empty or "Close" not in df:
            raise ToolError(f"No price history for {ticker}.")

        closes = df["Close"].dropna()
        return PriceHistory(
            ticker=ticker,
            dates=[d.strftime("%Y-%m-%d") for d in closes.index],
            closes=[float(c) for c in closes.values],
        )
