"""Market data via yfinance (Yahoo Finance).

Swap target: Alpha Vantage, Polygon.io, Finnhub. Any class implementing
`MarketDataProvider` can replace this.
"""
from __future__ import annotations

from datetime import datetime, timezone

import yfinance as yf

from app.models import MarketData
from app.tools.base import ToolError


class YFinanceMarketData:
    name = "yfinance"

    def get_market_data(self, ticker: str) -> MarketData:
        ticker = ticker.strip().upper()
        if not ticker or not ticker.replace(".", "").replace("-", "").isalnum():
            raise ToolError(f"Invalid ticker symbol: {ticker!r}")

        try:
            t = yf.Ticker(ticker)
            info = t.info or {}
        except Exception as exc:  # noqa: BLE001 - normalize any yfinance error
            raise ToolError(f"Market data lookup failed for {ticker}: {exc}") from exc

        # yfinance returns a near-empty dict for unknown tickers.
        price = (
            info.get("currentPrice")
            or info.get("regularMarketPrice")
            or info.get("previousClose")
        )
        if price is None and not info.get("shortName"):
            raise ToolError(f"No market data found for ticker {ticker}")

        return MarketData(
            ticker=ticker,
            name=info.get("longName") or info.get("shortName"),
            price=price,
            currency=info.get("currency"),
            market_cap=info.get("marketCap"),
            volume=info.get("volume") or info.get("regularMarketVolume"),
            pe_ratio=info.get("trailingPE"),
            fifty_two_week_high=info.get("fiftyTwoWeekHigh"),
            fifty_two_week_low=info.get("fiftyTwoWeekLow"),
            sector=info.get("sector"),
            industry=info.get("industry"),
            as_of=datetime.now(timezone.utc).isoformat(),
        )
