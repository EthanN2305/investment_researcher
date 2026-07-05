"""Bulk daily closes via Massive.com (formerly Polygon.io), for the screener.

One grouped-daily request returns closing prices for the ENTIRE US stock
market for one trading day, so a 6-month screen of 500+ tickers costs
~128 requests total — and results are cached on disk, so subsequent sweeps
only fetch the few days that are new.

Free tier is limited to 5 requests/minute; on HTTP 429 we sleep and retry,
which self-paces the initial backfill (~25 min once, then seconds).

Enable by setting MASSIVE_API_KEY in backend/.env.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Callable

import httpx

from app.config import settings
from app.tools.base import ToolError

logger = logging.getLogger("massive")

_CACHE_FILE = Path("massive_daily_cache.json")
_CACHE_LOCK = threading.Lock()

_CAL_WINDOW_DAYS = 190     # calendar days back (~128 trading days ≈ 6 months)
_RATE_LIMIT_SLEEP = 15.0   # seconds to wait after a 429 (free tier: 5 req/min)
_MAX_RETRIES_PER_DAY = 6
_HOLIDAY_CONFIRM_AGE = 3   # only cache "no data" for days at least this old

ProgressFn = Callable[[str, int, int, str | None], None]


def enabled() -> bool:
    return bool(settings.massive_api_key)


def _load_cache() -> dict[str, dict[str, float]]:
    try:
        with _CACHE_FILE.open() as f:
            return json.load(f)
    except Exception:  # noqa: BLE001 — missing/corrupt cache just means refetch
        return {}


def _save_cache(cache: dict[str, dict[str, float]], oldest_kept: str) -> None:
    pruned = {d: v for d, v in cache.items() if d >= oldest_kept}
    tmp = _CACHE_FILE.with_suffix(".tmp")
    with tmp.open("w") as f:
        json.dump(pruned, f)
    tmp.replace(_CACHE_FILE)


def _fetch_grouped_day(client: httpx.Client, day: str) -> dict[str, float] | None:
    """Closes for every US stock on one day; None = give up on this day."""
    url = (
        f"{settings.massive_base_url.rstrip('/')}"
        f"/v2/aggs/grouped/locale/us/market/stocks/{day}"
    )
    for attempt in range(_MAX_RETRIES_PER_DAY):
        try:
            resp = client.get(
                url,
                params={"adjusted": "true", "apiKey": settings.massive_api_key},
                timeout=30,
            )
        except httpx.HTTPError as exc:
            logger.warning("massive: network error for %s: %s", day, exc)
            time.sleep(2.0 * (attempt + 1))
            continue
        if resp.status_code == 429:
            logger.info("massive: 429 for %s; sleeping %.0fs (free-tier pacing)",
                        day, _RATE_LIMIT_SLEEP)
            time.sleep(_RATE_LIMIT_SLEEP)
            continue
        if resp.status_code in (401, 403):
            raise ToolError(
                f"Massive API rejected the key (HTTP {resp.status_code}). "
                "Check MASSIVE_API_KEY in backend/.env."
            )
        if resp.status_code != 200:
            logger.warning("massive: HTTP %d for %s", resp.status_code, day)
            time.sleep(2.0 * (attempt + 1))
            continue
        data = resp.json()
        results = data.get("results") or []
        out: dict[str, float] = {}
        for r in results:
            sym = r.get("T")
            close = r.get("c")
            if sym and close is not None:
                # Massive uses BRK.B; the universe uses Yahoo's BRK-B.
                out[sym.replace(".", "-")] = float(close)
        return out
    return None


def batch_closes(
    tickers: tuple[str, ...],
    progress: ProgressFn = lambda *a: None,
) -> dict[str, list[float]]:
    """~6 months of daily closes for `tickers` via grouped-daily requests.

    Raises ToolError on a rejected key so the caller can fall back to Yahoo.
    """
    if not enabled():
        raise ToolError("MASSIVE_API_KEY not configured")

    wanted = set(tickers)
    today = date.today()
    oldest = today - timedelta(days=_CAL_WINDOW_DAYS)
    days = [
        (oldest + timedelta(days=i)).isoformat()
        for i in range((today - oldest).days + 1)
        if (oldest + timedelta(days=i)).weekday() < 5  # skip weekends
    ]

    with _CACHE_LOCK:
        cache = _load_cache()
    to_fetch = [d for d in days if d not in cache]
    logger.info("massive: %d trading days, %d cached, %d to fetch",
                len(days), len(days) - len(to_fetch), len(to_fetch))

    total = len(days)
    done = total - len(to_fetch)
    progress("screening", done, total, None)

    fetched_any = False
    with httpx.Client() as client:
        for day in to_fetch:
            got = _fetch_grouped_day(client, day)
            if got is None:
                logger.warning("massive: giving up on %s", day)
            elif got:
                cache[day] = {t: c for t, c in got.items() if t in wanted}
                fetched_any = True
            else:
                # Empty result: market holiday, or today's bar not ready yet.
                age = (today - date.fromisoformat(day)).days
                if age >= _HOLIDAY_CONFIRM_AGE:
                    cache[day] = {}
                    fetched_any = True
            done += 1
            progress("screening", done, total, None)

    if fetched_any:
        with _CACHE_LOCK:
            _save_cache(cache, oldest.isoformat())

    closes: dict[str, list[float]] = {}
    for day in days:  # chronological — days list is already ascending
        day_closes = cache.get(day)
        if not day_closes:
            continue
        for t, c in day_closes.items():
            closes.setdefault(t, []).append(c)

    logger.info("massive: closes for %d/%d tickers", len(closes), len(wanted))
    return closes
