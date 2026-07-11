"""One-call LLM news deep-dive for the Learn-tab video.

Turns already-fetched articles into short-form-video beats: 1-2 stories
("what happened" + "how it likely moves the price"), an overall news-sentiment
score, and a one-line consumer/retail take. Grounding rules mirror the News
Agent's (judge substance not scary words, weight recency, never invent).

API budget: at most ONE Anthropic call per (ticker, day). Results are cached
in-process for the day; failures are cached for a short TTL so a downed
provider isn't hammered on every page view. This module never fetches news
itself and never raises — any failure returns None and the video falls back
to plain headline cards.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import date, datetime, timezone

from anthropic import Anthropic

from app.config import settings
from app.models import NewsItem

logger = logging.getLogger(__name__)

_MAX_ARTICLES = 8
_MAX_TOKENS = 700
_NEG_TTL_SECONDS = 600  # retry a failed analysis after 10 min, not per view

_SYSTEM = (
    "You are a careful equity-news analyst writing beats for a short-form "
    "stock video. You ground every statement only in the articles provided — "
    "never invented figures, dates, or events. You judge the substance of "
    "news, not the presence of scary words. This is education/entertainment "
    "for a general audience, never investment advice."
)

# The tool schema IS the structured-output contract (same pattern as
# app/tools/llm.py). Length caps are enforced again server-side in _shape.
_VIDEO_NEWS_TOOL = {
    "name": "emit_video_news",
    "description": "Emit the news deep-dive for a short-form stock video. "
                   "Call exactly once.",
    "input_schema": {
        "type": "object",
        "properties": {
            "stories": {
                "type": "array",
                "minItems": 1,
                "maxItems": 2,
                "description": "The 1-2 stories most likely to move the stock.",
                "items": {
                    "type": "object",
                    "properties": {
                        "headline": {
                            "type": "string",
                            "description": "Punchy on-screen headline, max 90 chars.",
                        },
                        "what_happened": {
                            "type": "string",
                            "description": "Plain-English what happened, 1-2 short "
                                           "sentences, max 200 chars. Keep any "
                                           "figures the article gives.",
                        },
                        "price_impact": {
                            "type": "string",
                            "description": "How this likely affects the share price "
                                           "and why, for a viewer with no finance "
                                           "background. Max 180 chars.",
                        },
                        "sentiment": {
                            "type": "string",
                            "enum": ["positive", "neutral", "negative"],
                            "description": "Directional impact on the stock. Judge "
                                           "substance, not scary words.",
                        },
                        "date": {
                            "type": "string",
                            "description": "ISO date (YYYY-MM-DD) copied from one "
                                           "of the supplied article dates.",
                        },
                    },
                    "required": ["headline", "what_happened", "price_impact",
                                 "sentiment", "date"],
                },
            },
            "sentiment_score": {
                "type": "number",
                "minimum": -1,
                "maximum": 1,
                "description": "Overall news mood for the stock: -1 very bearish "
                               "to 1 very bullish.",
            },
            "sentiment_label": {
                "type": "string",
                "description": "Short mood label, max 24 chars, e.g. "
                               "'Leaning bullish'.",
            },
            "consumer_take": {
                "type": "string",
                "description": "One casual line on how retail investors/consumers "
                               "likely feel, grounded in the coverage. Max 160 chars.",
            },
        },
        "required": ["stories", "sentiment_score", "sentiment_label",
                     "consumer_take"],
    },
}

# (ticker, ISO day) -> (timestamp, result-or-None). One entry per pick per day;
# entries from previous days are pruned on insert so this never grows.
_CACHE: dict[tuple[str, str], tuple[float, dict | None]] = {}
_LOCK = threading.Lock()
_client: Anthropic | None = None


def _get_client() -> Anthropic:
    global _client
    if _client is None:
        if not settings.anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set")
        _client = Anthropic(
            api_key=settings.anthropic_api_key,
            timeout=settings.llm_timeout_seconds,
            max_retries=settings.llm_max_retries,
        )
    return _client


def clear_cache() -> None:
    """Test hook — wipe the per-day analysis cache."""
    with _LOCK:
        _CACHE.clear()


def _cap(s: str, n: int) -> str:
    """Trim to n chars at a word boundary with an ellipsis (mirrors
    learn_brief._trim, redefined here to avoid a circular import)."""
    s = (s or "").strip()
    if len(s) <= n:
        return s
    cut = s[:n]
    sp = cut.rfind(" ")
    # No word boundary → drop a char so the ellipsis stays inside the cap.
    return (cut[:sp] if sp > 0 else cut[: n - 1]).rstrip(",.;:") + "…"


def _prompt(
    ticker: str,
    name: str | None,
    price: float | None,
    momentum_3mo: float | None,
    news: list[NewsItem],
) -> str:
    today = datetime.now(timezone.utc).date().isoformat()
    lines = "\n".join(
        f"- [{n.published_at or 'n/a'}] {n.title} ({n.source or 'unknown'})\n"
        f"  {(n.summary or '').strip()}".rstrip()
        for n in news[:_MAX_ARTICLES]
    )
    momentum = (
        f"{momentum_3mo * 100:+.1f}% over 3 months"
        if momentum_3mo is not None else "unknown"
    )
    price_s = f"${price:,.2f}" if price else "an unknown price"
    return (
        f"Today's date is {today}. Write the news deep-dive for a short-form "
        f"video about {name or ticker} ({ticker}), trading near {price_s} "
        f"with {momentum} momentum.\n\n"
        f"RECENT ARTICLES:\n{lines}\n\n"
        "Rules:\n"
        "- Pick the 1-2 stories most likely to move the stock. Skip "
        "promotional/listicle content and articles not actually about the "
        "company.\n"
        "- Base everything ONLY on the articles above; 'date' must be one of "
        "their dates.\n"
        "- Weight recent articles over older ones; judge substance, not "
        "scary words.\n"
        "- Keep every field inside its stated length cap — these render on a "
        "phone screen."
    )


def _shape(payload: dict) -> dict | None:
    """Validate + cap the tool output; None when nothing usable came back."""
    stories: list[dict] = []
    for s in (payload.get("stories") or [])[:2]:
        headline = _cap(str(s.get("headline") or ""), 90)
        what = _cap(str(s.get("what_happened") or ""), 200)
        if not headline or not what:
            continue
        sentiment = s.get("sentiment")
        stories.append({
            "headline": headline,
            "what_happened": what,
            "price_impact": _cap(str(s.get("price_impact") or ""), 180),
            "sentiment": sentiment
            if sentiment in ("positive", "neutral", "negative") else "neutral",
            "date": str(s.get("date") or "")[:10],
        })
    if not stories:
        return None
    try:
        score = max(-1.0, min(1.0, float(payload.get("sentiment_score", 0.0))))
    except (TypeError, ValueError):
        score = 0.0
    return {
        "stories": stories,
        "sentiment_score": score,
        "sentiment_label": _cap(str(payload.get("sentiment_label") or ""), 24)
        or "Mixed",
        "consumer_take": _cap(str(payload.get("consumer_take") or ""), 160),
    }


def _analyze(ticker, name, price, momentum_3mo, news, client) -> dict | None:
    try:
        cl = client or _get_client()
        resp = cl.messages.create(
            model=settings.anthropic_model,
            max_tokens=_MAX_TOKENS,
            system=_SYSTEM,
            tools=[_VIDEO_NEWS_TOOL],
            tool_choice={"type": "tool", "name": "emit_video_news"},
            messages=[{"role": "user",
                       "content": _prompt(ticker, name, price, momentum_3mo,
                                          news)}],
        )
    except Exception as exc:  # noqa: BLE001 — analysis is a nicety, never fatal
        logger.info("learn news: analysis unavailable for %s: %s", ticker, exc)
        return None
    payload = next(
        (b.input for b in resp.content
         if getattr(b, "type", "") == "tool_use"
         and getattr(b, "name", "") == "emit_video_news"),
        None,
    )
    return _shape(payload) if payload is not None else None


def analyze_news(
    ticker: str,
    name: str | None,
    price: float | None,
    momentum_3mo: float | None,
    news: list[NewsItem],
    *,
    client=None,
    today: date | None = None,
) -> dict | None:
    """The public entry point: day-cached, budget-capped, never raises."""
    if not news:
        return None
    key = (ticker.strip().upper(), (today or date.today()).isoformat())
    with _LOCK:
        hit = _CACHE.get(key)
        if hit is not None:
            ts, val = hit
            # Successes are good all day; failures retry after the TTL.
            if val is not None or (time.time() - ts) < _NEG_TTL_SECONDS:
                return val
    result = _analyze(ticker, name, price, momentum_3mo, news, client)
    with _LOCK:
        _CACHE[key] = (time.time(), result)
        for stale in [k for k in _CACHE if k[1] != key[1]]:
            del _CACHE[stale]
    return result
