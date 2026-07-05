"""Top-stock recommender — two-stage funnel over the S&P 500 + Nasdaq-100.

Stage 1 (screen): ~6 months of daily closes for the whole universe, from
Massive.com grouped-daily bars when MASSIVE_API_KEY is set (cached on disk),
otherwise batched Yahoo Finance spark requests. Each ticker gets a
momentum-quality score from 3-month/1-month returns, trend (above/below
50-day SMA), and RSI positioning. Penny stocks (< $5) are excluded.

Stage 2 (agents): the top screen survivors go through the same LangGraph
agent pipeline the research tab uses (quick depth: Technical Analysis +
Valuation agents + Recommendation synthesis). Picks are ranked by agent
stance (bullish > neutral > bearish), then confidence, then screen score,
and the top N are stored under one run_id.
"""
from __future__ import annotations

import logging
import math
import time
import uuid
from typing import Callable

import yfinance as yf
from sqlalchemy.orm import Session

from app.db_models import RecommendationItem
from app.summaries import run_pipeline_headless, short_summary
from app.tools import massive
from app.tools.base import ToolError
from app.tools.market_data import _make_session
from app.universe import UNIVERSE

logger = logging.getLogger("recommender")

MIN_PRICE = 5.0          # "no penny stocks"
MIN_HISTORY = 64         # need ~3 trading months for momentum math
CHUNK_SIZE = 40          # symbols per batched Yahoo spark request
DEFAULT_CANDIDATES = 20  # screen survivors sent to the agents
DEFAULT_TOP_N = 10

_SPARK_URL = "https://query1.finance.yahoo.com/v8/finance/spark"
_SPARK_RETRIES = 3
_CHUNK_PAUSE = 0.4       # polite gap between batch requests (seconds)

_STANCE_ORDER = {"bullish": 0, "neutral": 1, "bearish": 2}

ProgressFn = Callable[[str, int, int, str | None], None]
# progress(phase, completed, total, current_ticker)


def _noop_progress(phase: str, completed: int, total: int, current: str | None) -> None:
    pass


# --------------------------------------------------------------------------
# Stage 1 — technical screen
# --------------------------------------------------------------------------

def _rsi14(closes: list[float]) -> float | None:
    if len(closes) < 15:
        return None
    gains = losses = 0.0
    for prev, cur in zip(closes[-15:-1], closes[-14:]):
        delta = cur - prev
        if delta >= 0:
            gains += delta
        else:
            losses -= delta
    if losses == 0:
        return 100.0
    rs = (gains / 14) / (losses / 14)
    return 100.0 - 100.0 / (1.0 + rs)


def _score_ticker(closes: list[float]) -> dict | None:
    """Momentum-quality score; None = filtered out (penny stock/thin data)."""
    if len(closes) < MIN_HISTORY:
        return None
    last = closes[-1]
    if not last or last < MIN_PRICE or math.isnan(last):
        return None

    r3m = last / closes[-63] - 1 if closes[-63] else 0.0
    r1m = last / closes[-21] - 1 if closes[-21] else 0.0
    sma50 = sum(closes[-50:]) / 50
    above_sma50 = last > sma50
    rsi = _rsi14(closes)

    score = r3m + 0.5 * r1m + (0.05 if above_sma50 else -0.05)
    if rsi is not None:  # penalize exhaustion at either extreme
        if rsi > 75:
            score -= (rsi - 75) * 0.005
        elif rsi < 30:
            score -= (30 - rsi) * 0.005

    return {
        "price": round(last, 4),
        "score": round(score, 4),
        "momentum_3mo": round(r3m, 4),
        "momentum_1mo": round(r1m, 4),
        "above_sma50": above_sma50,
        "rsi": round(rsi, 1) if rsi is not None else None,
    }


def _yahoo_crumb(session) -> str | None:
    """Warm the session with Yahoo cookies, then fetch an API crumb.

    Yahoo now returns 401/429 on query1 endpoints hit by a cookie-less
    session — visiting fc.yahoo.com first sets the required cookies, and
    /v1/test/getcrumb issues the crumb the data endpoints expect.
    """
    try:
        session.get("https://fc.yahoo.com/", timeout=10)  # 404 is fine; sets cookies
        resp = session.get(
            "https://query1.finance.yahoo.com/v1/test/getcrumb", timeout=10
        )
        crumb = (resp.text or "").strip()
        if resp.status_code == 200 and crumb and "<" not in crumb:
            return crumb
    except Exception as exc:  # noqa: BLE001 — warmup is best-effort
        logger.info("screen: yahoo crumb warmup failed: %s", exc)
    return None


def _spark_closes(
    chunk: list[str], session, crumb: str | None = None
) -> dict[str, list[float]]:
    """One batched request to Yahoo's spark endpoint (many symbols per call).

    The browser-impersonating curl_cffi session is the same trick
    YFinanceMarketData uses to dodge Yahoo's bot checks — plain requests
    from a server get blocked, which is why unauthenticated yf.download
    sweeps come back empty.
    """
    params = {
        "symbols": ",".join(chunk),
        "range": "6mo",
        "interval": "1d",
    }
    if crumb:
        params["crumb"] = crumb
    resp = session.get(_SPARK_URL, params=params, timeout=20)
    if resp.status_code != 200:
        raise RuntimeError(f"spark HTTP {resp.status_code}")
    data = resp.json()
    out: dict[str, list[float]] = {}

    # Shape A: {"spark": {"result": [{"symbol": ..., "response": [chart]}]}}
    results = (data.get("spark") or {}).get("result") or []
    for r in results:
        symbol = r.get("symbol")
        responses = r.get("response") or []
        if not symbol or not responses:
            continue
        quote = ((responses[0].get("indicators") or {}).get("quote") or [{}])[0]
        closes = [c for c in (quote.get("close") or []) if c is not None]
        if closes:
            out[symbol] = [float(c) for c in closes]

    # Shape B: {"AAPL": {"symbol": "AAPL", "close": [...]}, ...}
    if not out:
        for symbol, r in data.items():
            if not isinstance(r, dict):
                continue
            closes = [c for c in (r.get("close") or []) if c is not None]
            if closes:
                out[symbol] = [float(c) for c in closes]
    return out


def _download_closes(chunk: list[str], session) -> dict[str, list[float]]:
    """Fallback: yf.download for one chunk (single-threaded, shared session)."""
    out: dict[str, list[float]] = {}
    try:
        df = yf.download(
            chunk, period="6mo", interval="1d", auto_adjust=True,
            group_by="ticker", progress=False, threads=False,
            session=session,
        )
    except Exception as exc:  # noqa: BLE001 — a bad chunk shouldn't kill the run
        logger.warning("screen: yf.download failed (%s…): %s", chunk[0], exc)
        return out
    for t in chunk:
        try:
            series = (df[t]["Close"] if len(chunk) > 1 else df["Close"]).dropna()
            if len(series):
                out[t] = [float(c) for c in series.values]
        except Exception:  # noqa: BLE001 — ticker missing from frame
            continue
    return out


def _batch_closes(
    tickers: tuple[str, ...], progress: ProgressFn
) -> dict[str, list[float]]:
    """Six months of daily closes for the whole universe, in batches.

    Spark first (true multi-symbol batching, ~13 requests for the whole
    universe), with per-chunk retry/backoff on rate limits and a
    yf.download fallback per chunk.
    """
    session = _make_session()
    crumb = _yahoo_crumb(session) if session is not None else None
    out: dict[str, list[float]] = {}
    errors: list[str] = []
    total = len(tickers)
    done = 0
    for i in range(0, total, CHUNK_SIZE):
        chunk = list(tickers[i : i + CHUNK_SIZE])
        got: dict[str, list[float]] = {}
        if session is not None:
            for attempt in range(_SPARK_RETRIES):
                try:
                    got = _spark_closes(chunk, session, crumb)
                    if got:
                        break
                except Exception as exc:  # noqa: BLE001 — retry with fresh session
                    logger.info(
                        "screen: spark attempt %d failed (%s…): %s",
                        attempt + 1, chunk[0], exc,
                    )
                    errors.append(str(exc))
                time.sleep(1.5 * (attempt + 1))
                session = _make_session()
                crumb = _yahoo_crumb(session) if session is not None else None
        if not got:
            got = _download_closes(chunk, session)
        if not got:
            logger.warning("screen: no data for chunk starting %s", chunk[0])
        out.update(got)
        done += len(chunk)
        progress("screening", done, total, None)
        time.sleep(_CHUNK_PAUSE)
    logger.info("screen: got closes for %d/%d tickers", len(out), total)
    if not out:
        detail = f" Last Yahoo error: {errors[-1]}" if errors else ""
        raise RuntimeError(
            "Screening got no price data from Yahoo Finance — every batch "
            f"failed.{detail} Set MASSIVE_API_KEY in backend/.env to use "
            "Massive.com instead, or wait a few minutes and retry."
        )
    return out


def _universe_closes(progress: ProgressFn) -> dict[str, list[float]]:
    """Closes for the whole universe: Massive.com first (if configured),
    Yahoo Finance otherwise or as fallback."""
    if massive.enabled():
        try:
            closes = massive.batch_closes(UNIVERSE, progress)
            if closes:
                return closes
            logger.warning("screen: Massive returned no data; trying Yahoo")
        except ToolError as exc:
            logger.warning("screen: Massive failed (%s); trying Yahoo", exc)
    return _batch_closes(UNIVERSE, progress)


def screen_universe(
    top_n: int = DEFAULT_CANDIDATES, progress: ProgressFn = _noop_progress
) -> list[dict]:
    """Rank the universe by momentum-quality score; return the top slice."""
    closes_by_ticker = _universe_closes(progress)
    scored: list[dict] = []
    for ticker, closes in closes_by_ticker.items():
        s = _score_ticker(closes)
        if s is not None:
            scored.append({"ticker": ticker, **s})
    scored.sort(key=lambda d: d["score"], reverse=True)
    logger.info(
        "screen: %d/%d tickers scored, taking top %d",
        len(scored), len(UNIVERSE), top_n,
    )
    return scored[:top_n]


# --------------------------------------------------------------------------
# Stage 2 — agent analysis + ranking
# --------------------------------------------------------------------------

def run_recommendations(
    db: Session,
    graph,
    *,
    candidates: int = DEFAULT_CANDIDATES,
    top_n: int = DEFAULT_TOP_N,
    progress: ProgressFn = _noop_progress,
) -> list[RecommendationItem]:
    """Full sweep: screen → agent pipeline per candidate → store top N."""
    shortlist = screen_universe(candidates, progress)
    if not shortlist:
        raise RuntimeError(
            "Screening fetched prices but every ticker was filtered out "
            "(need ≥64 days of history and price ≥ $5) — the price data "
            "may be incomplete. Try again shortly."
        )

    analyzed: list[dict] = []
    total = len(shortlist)
    for idx, cand in enumerate(shortlist):
        progress("analyzing", idx, total, cand["ticker"])
        try:
            report = run_pipeline_headless(
                graph, cand["ticker"], None, depth="quick", lens="balanced"
            )
        except Exception as exc:  # noqa: BLE001 — skip, don't abort the sweep
            logger.warning("recommend: pipeline failed for %s: %s",
                           cand["ticker"], exc)
            report = None
        if report is None:
            analyzed.append({**cand, "stance": "neutral", "confidence": 0.0,
                             "summary": "Agent analysis unavailable."})
        else:
            analyzed.append({
                **cand,
                "stance": report.recommendation.stance,
                "confidence": report.recommendation.confidence,
                "summary": short_summary(report),
            })
    progress("analyzing", total, total, None)

    analyzed.sort(key=lambda d: (
        _STANCE_ORDER.get(d["stance"], 1), -d["confidence"], -d["score"],
    ))
    picks = analyzed[:top_n]

    run_id = uuid.uuid4().hex
    items = [
        RecommendationItem(
            run_id=run_id, rank=i + 1, ticker=p["ticker"], price=p["price"],
            screen_score=p["score"], momentum_3mo=p["momentum_3mo"],
            stance=p["stance"], confidence=p["confidence"],
            summary=p["summary"][:600],
        )
        for i, p in enumerate(picks)
    ]
    db.add_all(items)
    db.commit()
    logger.info("recommend: stored %d picks (run %s)", len(items), run_id)
    return items
