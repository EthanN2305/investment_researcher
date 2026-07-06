"""Market data via yfinance (Yahoo Finance).

Yahoo aggressively rate-limits the heavy `quoteSummary` endpoint that
`Ticker.info` uses (HTTP 429). This implementation is built to survive that:

  1. Primary numbers come from `fast_info`, which uses the lighter chart
     endpoint and is far less throttled.
  2. A browser-impersonating `curl_cffi` session (when available) obtains the
     crumb/cookies Yahoo now requires, cutting 429s dramatically.
  3. Calls retry with exponential backoff on rate-limit responses.
  4. Results are cached in-process for a short TTL so repeated lookups of the
     same ticker don't re-hit Yahoo.
  5. Optional enrichment (sector, industry, P/E, full name) comes from `.info`
     but is best-effort — if it 429s we still return the core report.

Swap target: Alpha Vantage, Polygon.io, Finnhub. Any class implementing
`MarketDataProvider` can replace this.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

import yfinance as yf

from app.models import MarketData
from app.tools.base import RateLimitError, ToolError

logger = logging.getLogger("market_data")

# --- Browser-impersonating session (best-effort) ----------------------------
try:  # curl_cffi lets us pass Yahoo's bot checks and get a crumb.
    from curl_cffi import requests as _cffi

    def _make_session():
        return _cffi.Session(impersonate="chrome")
except Exception:  # noqa: BLE001 - curl_cffi optional / import may fail
    def _make_session():
        return None


# --- Tiny in-process TTL cache ---------------------------------------------
_CACHE: dict[str, tuple[float, MarketData]] = {}
_CACHE_TTL_SECONDS = 300  # 5 minutes; live enough for a research report.

_MAX_RETRIES = 3
_BASE_BACKOFF = 1.5  # seconds


def _is_rate_limit(exc: Exception) -> bool:
    text = str(exc).lower()
    return "429" in text or "too many requests" in text or "rate limit" in text


class YFinanceMarketData:
    name = "yfinance"

    def __init__(self, cache_ttl: int = _CACHE_TTL_SECONDS) -> None:
        self._ttl = cache_ttl

    def get_market_data(self, ticker: str) -> MarketData:
        ticker = ticker.strip().upper()
        if not ticker or not ticker.replace(".", "").replace("-", "").isalnum():
            raise ToolError(f"Invalid ticker symbol: {ticker!r}")

        cached = self._from_cache(ticker)
        if cached is not None:
            return cached

        data = self._fetch_with_retry(ticker)
        _CACHE[ticker] = (time.time(), data)
        return data

    # -- internals ----------------------------------------------------------
    def _from_cache(self, ticker: str) -> MarketData | None:
        hit = _CACHE.get(ticker)
        if hit and (time.time() - hit[0]) < self._ttl:
            return hit[1]
        return None

    def _fetch_with_retry(self, ticker: str) -> MarketData:
        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                return self._fetch_once(ticker)
            except RateLimitError as exc:
                last_exc = exc
                if attempt < _MAX_RETRIES - 1:
                    delay = _BASE_BACKOFF * (2**attempt)
                    logger.warning(
                        "yfinance 429 for %s; retrying in %.1fs (attempt %d/%d)",
                        ticker, delay, attempt + 1, _MAX_RETRIES,
                    )
                    time.sleep(delay)
        raise RateLimitError(
            f"Yahoo Finance is rate-limiting requests for {ticker}. "
            "Please try again in a minute."
        ) from last_exc

    def _fetch_once(self, ticker: str) -> MarketData:
        session = _make_session()
        try:
            t = yf.Ticker(ticker, session=session) if session else yf.Ticker(ticker)
        except TypeError:
            # Older/newer yfinance may not accept a session kwarg.
            t = yf.Ticker(ticker)

        # 1) Core numbers from the light-weight fast_info endpoint.
        fast = self._read_fast_info(t, ticker)

        # 2) Best-effort enrichment from the heavier .info endpoint.
        info = self._read_info_best_effort(t)

        price = fast.get("price") or info.get("currentPrice") or info.get(
            "regularMarketPrice"
        ) or info.get("previousClose")

        name = info.get("longName") or info.get("shortName")

        if price is None and name is None and not info:
            raise ToolError(f"No market data found for ticker {ticker}")

        return MarketData(
            ticker=ticker,
            name=name,
            price=price,
            currency=fast.get("currency") or info.get("currency"),
            market_cap=fast.get("market_cap") or info.get("marketCap"),
            volume=fast.get("volume")
            or info.get("volume")
            or info.get("regularMarketVolume"),
            pe_ratio=info.get("trailingPE"),
            fifty_two_week_high=fast.get("year_high") or info.get("fiftyTwoWeekHigh"),
            fifty_two_week_low=fast.get("year_low") or info.get("fiftyTwoWeekLow"),
            sector=info.get("sector"),
            industry=info.get("industry"),
            business_summary=info.get("longBusinessSummary"),
            employees=_as_int(info.get("fullTimeEmployees")),
            headquarters=_headquarters(info),
            website=info.get("website"),
            as_of=datetime.now(timezone.utc).isoformat(),
        )

    def _read_fast_info(self, t: "yf.Ticker", ticker: str) -> dict:
        """Read fast_info; raise RateLimitError on 429, tolerate other misses."""
        try:
            fi = t.fast_info
            return {
                "price": _safe(fi, "last_price"),
                "currency": _safe(fi, "currency"),
                "market_cap": _safe(fi, "market_cap"),
                "volume": _safe(fi, "last_volume")
                or _safe(fi, "ten_day_average_volume"),
                "year_high": _safe(fi, "year_high"),
                "year_low": _safe(fi, "year_low"),
            }
        except Exception as exc:  # noqa: BLE001
            if _is_rate_limit(exc):
                raise RateLimitError(str(exc)) from exc
            logger.info("fast_info unavailable for %s: %s", ticker, exc)
            return {}

    def _read_info_best_effort(self, t: "yf.Ticker") -> dict:
        """Read .info but never fail the whole request because of it."""
        try:
            return t.info or {}
        except Exception as exc:  # noqa: BLE001
            if _is_rate_limit(exc):
                # Enrichment only — log and continue with fast_info numbers.
                logger.info(".info rate-limited; continuing with fast_info only")
            else:
                logger.info(".info unavailable: %s", exc)
            return {}


def _safe(obj, attr):
    """fast_info fields can raise (not return None) when missing; normalize that."""
    try:
        return getattr(obj, attr)
    except Exception:  # noqa: BLE001
        return None


def _as_int(v) -> int | None:
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _headquarters(info: dict) -> str | None:
    """"City, State" (US) or "City, Country" — best-effort from .info."""
    city = info.get("city")
    region = info.get("state") or info.get("country")
    parts = [p for p in (city, region) if p]
    return ", ".join(parts) if parts else None
