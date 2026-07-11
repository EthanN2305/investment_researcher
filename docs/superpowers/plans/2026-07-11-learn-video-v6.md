# Learn Video v6 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Learn-tab "Stock of the Day" short punchier (quiz hook, real price chart, big-story news deep-dive, sentiment gauge, kinetic pacing) with one strictly-budgeted LLM news analysis per (ticker, day).

**Architecture:** A new `learn_news.py` module makes ONE cached Anthropic forced-tool call over already-fetched articles; `learn_brief.py` becomes the single memoized fetch point (1 NewsAPI call, 1 yfinance history call, ≤1 LLM call per ticker/day) and feeds two new brief keys (`news_analysis`, `price_history`) through the router into the Remotion composition, which gains/reworks scenes with graceful fallbacks to today's behavior.

**Tech Stack:** FastAPI + pydantic backend, Anthropic SDK (forced tool call), yfinance, Remotion 4 / React 18 frontend, pytest.

**Spec:** `docs/superpowers/specs/2026-07-11-learn-video-v6-design.md`

## Global Constraints

- **API budget (hard):** per (ticker, day): exactly 1 NewsAPI fetch (`get_news(ticker, limit=8)`), ≤1 Anthropic call (day-cached; failures negative-cached with a 600s TTL), 1 yfinance history fetch. All shared via a memoized `build_brief`.
- Every new datum is optional; every scene keeps the pre-v6 behavior as its fallback. A render must never fail because of a missing NEWSAPI/ANTHROPIC key or throttled yfinance.
- Nothing fabricated: LLM output is grounded only in supplied articles; grounding rules mirror `claims_from_news` in `backend/app/tools/llm.py`.
- Backend tests: `cd backend && .venv/bin/python -m pytest tests/test_learn_video.py -v`. Full suite: `.venv/bin/python -m pytest tests -q`.
- Frontend check: `cd frontend && npm run build` must pass.
- Scene ids stay stable (`hook`, `ticker`, `about`, `details`, `momentum`, `news`, `sentiment`, `why`, `confidence`, `outro`) so narration/voiceover plumbing keys keep working. `sentiment` is the only conditionally-present scene.
- Match each file's existing comment density and style (this repo comments the "why" generously).

---

### Task 1: `learn_news.analyze_news` — cached one-call LLM news deep-dive

**Files:**
- Create: `backend/app/learn_news.py`
- Test: `backend/tests/test_learn_video.py` (new file)

**Interfaces:**
- Consumes: `app.config.settings` (`anthropic_api_key`, `anthropic_model`, `llm_timeout_seconds`, `llm_max_retries`), `app.models.NewsItem`.
- Produces: `analyze_news(ticker: str, name: str | None, price: float | None, momentum_3mo: float | None, news: list[NewsItem], *, client=None, today: date | None = None) -> dict | None` and `clear_cache() -> None`. Result shape:
  `{"stories": [{"headline", "what_happened", "price_impact", "sentiment", "date"}], "sentiment_score": float(-1..1), "sentiment_label": str, "consumer_take": str}`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_learn_video.py`:

```python
"""Learn-tab v6: LLM news deep-dive, brief API budget, narration beats."""
from datetime import date
from types import SimpleNamespace

import pytest

from app import learn_news
from app.models import NewsItem


# --- helpers -----------------------------------------------------------------

def _fake_client(payload, calls, fail=False):
    """A stand-in Anthropic client: records calls, returns a forced tool block."""
    block = SimpleNamespace(type="tool_use", name="emit_video_news", input=payload)
    resp = SimpleNamespace(content=[block])

    class _Messages:
        def create(self, **kwargs):
            calls.append(kwargs)
            if fail:
                raise RuntimeError("provider down")
            return resp

    return SimpleNamespace(messages=_Messages())


PAYLOAD = {
    "stories": [
        {
            "headline": "Chipmaker beats on Q2 earnings",
            "what_happened": "Quarterly revenue came in at $8.1B, up 38% year over "
                             "year, ahead of Wall Street estimates.",
            "price_impact": "Beats like this usually push the stock higher because "
                            "analysts raise their forecasts.",
            "sentiment": "positive",
            "date": "2026-07-10",
        }
    ],
    "sentiment_score": 0.6,
    "sentiment_label": "Leaning bullish",
    "consumer_take": "Retail investors are hyped about the AI demand story.",
}

NEWS = [
    NewsItem(title="Chipmaker beats on Q2 earnings", url="https://x.test/1",
             source="Reuters", published_at="2026-07-10T12:00:00Z",
             summary="Revenue of $8.1B beat estimates."),
    NewsItem(title="Sector roundup", url="https://x.test/2", source="Blog",
             published_at="2026-07-09T09:00:00Z", summary="General market chatter."),
]

TODAY = date(2026, 7, 11)


@pytest.fixture(autouse=True)
def _fresh_news_cache():
    learn_news.clear_cache()
    yield
    learn_news.clear_cache()


# --- analyze_news --------------------------------------------------------------

def test_analyze_news_shapes_output():
    calls = []
    out = learn_news.analyze_news(
        "MU", "Micron", 100.0, 0.22, NEWS,
        client=_fake_client(PAYLOAD, calls), today=TODAY)
    assert len(calls) == 1
    assert out["stories"][0]["headline"] == "Chipmaker beats on Q2 earnings"
    assert out["stories"][0]["sentiment"] == "positive"
    assert out["sentiment_score"] == 0.6
    assert out["sentiment_label"] == "Leaning bullish"
    # Forced tool call, small budget.
    assert calls[0]["tool_choice"] == {"type": "tool", "name": "emit_video_news"}
    assert calls[0]["max_tokens"] <= 700


def test_analyze_news_caps_lengths_and_clamps_score():
    calls = []
    noisy = {
        "stories": [{
            "headline": "H" * 300,
            "what_happened": "w " * 300,
            "price_impact": "p " * 300,
            "sentiment": "bogus",
            "date": "2026-07-10T12:00:00Z",
        }],
        "sentiment_score": 7,
        "sentiment_label": "L" * 100,
        "consumer_take": "c " * 300,
    }
    out = learn_news.analyze_news(
        "MU", None, None, None, NEWS,
        client=_fake_client(noisy, calls), today=TODAY)
    s = out["stories"][0]
    assert len(s["headline"]) <= 90
    assert len(s["what_happened"]) <= 200
    assert len(s["price_impact"]) <= 180
    assert s["sentiment"] == "neutral"          # unknown value coerced
    assert s["date"] == "2026-07-10"            # ISO date only
    assert out["sentiment_score"] == 1.0        # clamped to [-1, 1]
    assert len(out["sentiment_label"]) <= 24
    assert len(out["consumer_take"]) <= 160


def test_analyze_news_cached_per_ticker_day():
    calls = []
    client = _fake_client(PAYLOAD, calls)
    a = learn_news.analyze_news("MU", "Micron", 100.0, 0.2, NEWS,
                                client=client, today=TODAY)
    b = learn_news.analyze_news("MU", "Micron", 100.0, 0.2, NEWS,
                                client=client, today=TODAY)
    assert len(calls) == 1                      # ONE API call for the day
    assert a is b


def test_analyze_news_failure_returns_none_and_negative_caches():
    calls = []
    client = _fake_client(PAYLOAD, calls, fail=True)
    assert learn_news.analyze_news("MU", None, None, None, NEWS,
                                   client=client, today=TODAY) is None
    assert learn_news.analyze_news("MU", None, None, None, NEWS,
                                   client=client, today=TODAY) is None
    assert len(calls) == 1                      # failure cached, no hammering


def test_analyze_news_without_news_makes_no_call():
    calls = []
    out = learn_news.analyze_news("MU", None, None, None, [],
                                  client=_fake_client(PAYLOAD, calls), today=TODAY)
    assert out is None and calls == []


def test_analyze_news_unusable_stories_returns_none():
    calls = []
    empty = {**PAYLOAD, "stories": [{"headline": "", "what_happened": ""}]}
    out = learn_news.analyze_news("MU", None, None, None, NEWS,
                                  client=_fake_client(empty, calls), today=TODAY)
    assert out is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_learn_video.py -v`
Expected: FAIL — `ImportError: cannot import name 'learn_news'` (module doesn't exist).

- [ ] **Step 3: Implement `backend/app/learn_news.py`**

```python
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
    return (cut[:sp] if sp > 0 else cut).rstrip(",.;:") + "…"


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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_learn_video.py -v`
Expected: all 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/learn_news.py backend/tests/test_learn_video.py
git commit -m "feat: cached one-call LLM news deep-dive for learn videos"
```

---

### Task 2: `learn_brief` — single news fetch, real price history, memoized brief

**Files:**
- Modify: `backend/app/learn_brief.py`
- Test: `backend/tests/test_learn_video.py` (append)

**Interfaces:**
- Consumes: `learn_news.analyze_news` (Task 1 signature), `app.tools.prices.YFinancePriceHistory.get_history(ticker, period) -> PriceHistory` (`.dates: list[str]`, `.closes: list[float]`).
- Produces:
  - `fetch_news(ticker: str, limit: int = 8) -> list[NewsItem]` (best-effort, `[]` on failure)
  - `news_cards(items: list[NewsItem], limit: int = 3) -> list[dict]` (pure; replaces `recent_news`, same output shape `{title, source, when}`)
  - `price_history(ticker: str, story_dates: list[str]) -> dict` → `{"points": [{"d": str, "c": float}], "events": [{"i": int, "d": str}]}` or `{}`
  - `build_brief(pick) -> dict` now returns keys `details, news, reasons, news_analysis, price_history` and is memoized per (ticker, day); `clear_brief_cache() -> None` for tests. The `want_news` parameter is removed (no caller used it).

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_learn_video.py`:

```python
# --- learn_brief: API budget + price history ----------------------------------

from app import learn_brief
from app.models import PriceHistory

ANALYSIS = {
    "stories": [{
        "headline": "Chipmaker beats on Q2 earnings",
        "what_happened": "Revenue of $8.1B beat estimates.",
        "price_impact": "Beats usually push the stock higher.",
        "sentiment": "positive",
        "date": "2026-07-10",
    }],
    "sentiment_score": 0.6,
    "sentiment_label": "Leaning bullish",
    "consumer_take": "Retail is hyped.",
}


def _pick(ticker="MU"):
    return SimpleNamespace(
        ticker=ticker, price=100.0, momentum_3mo=0.22, screen_score=8.0,
        stance="bullish", confidence=0.7, rank=1, summary="Strong setup.")


@pytest.fixture(autouse=True)
def _fresh_brief_cache():
    learn_brief.clear_brief_cache()
    yield
    learn_brief.clear_brief_cache()


def test_build_brief_fetches_news_once_and_memoizes(monkeypatch):
    calls = {"news": 0}

    def fake_get_news(ticker, limit=8):
        calls["news"] += 1
        assert limit == 8
        return NEWS

    monkeypatch.setattr(learn_brief._NEWS, "get_news", fake_get_news)
    monkeypatch.setattr(learn_brief, "stock_details",
                        lambda t, p: {"name": "Micron", "sector": "Technology"})
    monkeypatch.setattr(learn_brief.learn_news, "analyze_news",
                        lambda *a, **k: dict(ANALYSIS))
    monkeypatch.setattr(learn_brief, "price_history",
                        lambda t, d: {"points": [], "events": []})

    b1 = learn_brief.build_brief(_pick())
    b2 = learn_brief.build_brief(_pick())
    assert calls["news"] == 1               # ONE NewsAPI call, brief memoized
    assert b1 is b2
    assert b1["news_analysis"]["stories"]
    assert b1["news"][0]["title"] == "Chipmaker beats on Q2 earnings"


def test_build_brief_survives_all_providers_down(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("down")

    monkeypatch.setattr(learn_brief._NEWS, "get_news", boom)
    monkeypatch.setattr(learn_brief._MARKET, "get_market_data", boom)
    monkeypatch.setattr(learn_brief._HISTORY, "get_history", boom)
    b = learn_brief.build_brief(_pick("AMD"))
    assert b["news"] == [] and b["news_analysis"] == {} and b["price_history"] == {}
    assert b["reasons"]                     # deterministic reasons still there


def test_price_history_downsamples_and_pins_events(monkeypatch):
    dates = [f"2026-{4 + i // 30:02d}-{i % 30 + 1:02d}" for i in range(90)]
    closes = [100.0 + i for i in range(90)]
    monkeypatch.setattr(
        learn_brief._HISTORY, "get_history",
        lambda t, period="3mo": PriceHistory(ticker=t, dates=dates,
                                             closes=closes))
    h = learn_brief.price_history("MU", ["2026-05-15", ""])
    assert 2 <= len(h["points"]) <= 61
    assert h["points"][-1]["d"] == dates[-1]        # last close always kept
    assert len(h["events"]) == 1                    # empty date skipped
    ev = h["events"][0]
    assert h["points"][ev["i"]]["d"] >= "2026-05-15"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_learn_video.py -v`
Expected: new tests FAIL — `AttributeError: module 'app.learn_brief' has no attribute 'clear_brief_cache'` (and `_HISTORY`).

- [ ] **Step 3: Implement the `learn_brief` changes**

In `backend/app/learn_brief.py`:

3a. Update imports and module setup (top of file):

```python
import logging
import re
import threading
from datetime import date, datetime, timezone

from app import learn_news
from app.tools.market_data import YFinanceMarketData
from app.tools.news import NewsAPINews
from app.tools.prices import YFinancePriceHistory

logger = logging.getLogger(__name__)

# Instantiated lazily and reused (all tools cache internally).
_MARKET = YFinanceMarketData()
_NEWS = NewsAPINews()
_HISTORY = YFinancePriceHistory()
```

3b. Replace the whole `recent_news` function with a fetch + pure-shaping pair:

```python
def fetch_news(ticker: str, limit: int = 8) -> list:
    """The ONE news fetch per brief — shared by the headline cards and the
    LLM analysis so the NewsAPI budget stays at a single call. Best-effort."""
    try:
        return _NEWS.get_news(ticker, limit=limit)
    except Exception as exc:  # noqa: BLE001
        logger.info("learn brief: news unavailable for %s: %s", ticker, exc)
        return []


def news_cards(items: list, limit: int = 3) -> list[dict]:
    """Most-recent headlines, trimmed for on-screen use. Pure — no fetching."""
    dated = sorted(
        items,
        key=lambda n: (_parse_dt(n.published_at) or datetime.min.replace(
            tzinfo=timezone.utc)),
        reverse=True,
    )
    out: list[dict] = []
    for n in dated[:limit]:
        title = _trim(n.title, 90)
        if not title or title == "(untitled)":
            continue
        out.append({
            "title": title,
            "source": n.source or "News",
            "when": _time_ago(n.published_at),
        })
    return out
```

3c. Add `price_history` after `news_cards`:

```python
def price_history(ticker: str, story_dates: list[str]) -> dict:
    """Real 3-month closes for the chart scene, downsampled to ≤60 points,
    with each analyzed story's date pinned to the nearest sampled point so
    the video can mark where the news broke. Best-effort: {} on any failure."""
    try:
        hist = _HISTORY.get_history(ticker, period="3mo")
    except Exception as exc:  # noqa: BLE001
        logger.info("learn brief: price history unavailable for %s: %s",
                    ticker, exc)
        return {}
    dates, closes = hist.dates, hist.closes
    if len(closes) < 2:
        return {}
    n = len(closes)
    step = max(1, (n + 59) // 60)
    idx = list(range(0, n, step))
    if idx[-1] != n - 1:  # the latest close is the story — always keep it
        idx.append(n - 1)
    points = [{"d": dates[i], "c": round(closes[i], 2)} for i in idx]
    events = []
    for d in story_dates:
        if not d:
            continue
        pos = next((j for j, p in enumerate(points) if p["d"] >= d), None)
        events.append({"i": pos if pos is not None else len(points) - 1,
                       "d": d})
    return {"points": points, "events": events}
```

3d. Replace `build_brief` (and its section comment) with the memoized version:

```python
# --- the full brief ----------------------------------------------------------

# One brief per (ticker, day): /learn/stock-of-the-day, /learn/shuffle,
# /learn/voiceover and /learn/render all reuse it, so the day's upstream
# budget stays at 1 news fetch + 1 history fetch + ≤1 LLM call. Entries from
# previous days are pruned on insert, so this holds at most ~10 tickers.
_BRIEF_CACHE: dict[tuple[str, str], dict] = {}
_BRIEF_LOCK = threading.Lock()


def clear_brief_cache() -> None:
    """Test hook — wipe the per-day brief cache."""
    with _BRIEF_LOCK:
        _BRIEF_CACHE.clear()


def build_brief(pick) -> dict:
    """Assemble everything the richer video needs. `pick` is a
    StockOfTheDayOut (or anything with the same attributes)."""
    key = (pick.ticker.strip().upper(), date.today().isoformat())
    with _BRIEF_LOCK:
        cached = _BRIEF_CACHE.get(key)
    if cached is not None:
        return cached

    details = stock_details(pick.ticker, pick.price)
    items = fetch_news(pick.ticker)
    analysis = learn_news.analyze_news(
        pick.ticker, details.get("name"), pick.price, pick.momentum_3mo,
        items) or {}
    history = price_history(
        pick.ticker, [s.get("date") for s in analysis.get("stories", [])])
    brief = {
        "details": details,
        "news": news_cards(items),
        "reasons": why_reasons(pick, details),
        "news_analysis": analysis,
        "price_history": history,
    }
    with _BRIEF_LOCK:
        _BRIEF_CACHE[key] = brief
        for stale in [k for k in _BRIEF_CACHE if k[1] != key[1]]:
            del _BRIEF_CACHE[stale]
    return brief
```

3e. Fix the one internal caller: in `build_brief`'s old body `recent_news` no longer exists — confirm with `grep -n "recent_news\|want_news" backend/app` that no references remain (the router calls `build_brief(out)` / `build_brief(pick)` with no second arg already).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_learn_video.py -v`
Expected: all tests PASS.

- [ ] **Step 5: Run the full backend suite (guard against regressions)**

Run: `cd backend && .venv/bin/python -m pytest tests -q`
Expected: PASS (no other module imports `recent_news`).

- [ ] **Step 6: Commit**

```bash
git add backend/app/learn_brief.py backend/tests/test_learn_video.py
git commit -m "feat: memoized brief with single news fetch, LLM analysis + real price history"
```

---

### Task 3: Narration beats — quiz hook, big story, sentiment

**Files:**
- Modify: `backend/app/learn_brief.py` (`build_narration` only)
- Test: `backend/tests/test_learn_video.py` (append)

**Interfaces:**
- Consumes: brief dict from Task 2 (`news_analysis` key).
- Produces: `build_narration(pick, brief, duration_sec)` unchanged signature; may now emit a `"sentiment"` key (only when analysis exists). Scene ids: `hook, ticker, about, details, momentum, news, sentiment, why, confidence, outro`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_learn_video.py`:

```python
# --- narration beats ------------------------------------------------------------

def _brief(with_analysis=True):
    return {
        "details": {"name": "Micron", "sector": "Technology",
                    "about": "Micron makes memory chips.",
                    "about_short": "Micron makes memory chips.",
                    "market_cap": "$120.00B", "range_pos": 80},
        "news": [{"title": "Chipmaker beats on Q2 earnings",
                  "source": "Reuters", "when": "1d ago"}],
        "reasons": [],
        "news_analysis": dict(ANALYSIS) if with_analysis else {},
        "price_history": {},
    }


def test_narration_quiz_hook_and_sentiment_beat():
    lines = learn_brief.build_narration(_pick(), _brief(), 30)
    assert lines["hook"].startswith("Can you guess")
    assert "sentiment" in lines
    assert "Leaning bullish" in lines["sentiment"]
    assert "Retail is hyped." in lines["sentiment"]
    # The news beat tells the story, not just a headline.
    assert "Revenue of $8.1B beat estimates." in lines["news"]
    assert "Beats usually push the stock higher." in lines["news"]


def test_narration_without_analysis_falls_back():
    lines = learn_brief.build_narration(_pick(), _brief(with_analysis=False), 30)
    assert "sentiment" not in lines            # scene will be skipped entirely
    assert "Chipmaker beats on Q2 earnings" in lines["news"]  # old headline read


def test_narration_long_cut_adds_second_story():
    brief = _brief()
    brief["news_analysis"]["stories"].append({
        "headline": "New fab announced", "what_happened": "A new fab is planned.",
        "price_impact": "", "sentiment": "positive", "date": "2026-07-09"})
    lines = learn_brief.build_narration(_pick(), brief, 65)
    assert "A new fab is planned." in lines["news"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_learn_video.py -v`
Expected: the 3 new tests FAIL (hook is the old "Alright, let's talk…" line; no `sentiment` key).

- [ ] **Step 3: Update `build_narration` in `backend/app/learn_brief.py`**

Replace the `lines["hook"]` and `lines["ticker"]` assignments:

```python
    # Quiz-style cold open: the visuals show hint chips (sector / size /
    # momentum) while this plays, so the words tee up the guessing game.
    sector_hint = details.get("sector")
    lines["hook"] = (
        "Can you guess today's A.I. stock of the day? "
        + (f"Here's a hint — it's a {sector_hint} name!" if sector_hint
           else "Here are your hints!")
    )

    lines["ticker"] = f"It's {t}!"
    if pick.price:
        lines["ticker"] += f" Trading around {pick.price:,.0f} dollars right now."
```

Replace the `lines["momentum"]` block's first sentence so it narrates the real chart (keep the long-cut screen-score sentence exactly as is):

```python
    if pick.momentum_3mo is not None:
        lines["momentum"] = (
            f"Check out this chart — it's {'up' if up else 'down'} about "
            f"{move} percent over the last three months!")
        if long:
            lines["momentum"] += (
                f" Its technical screen score? A solid {pick.screen_score:.0f} "
                "out of ten.")
    else:
        lines["momentum"] = ""
```

Replace the `if news:` news-beat block with the deep-dive version plus the new sentiment beat:

```python
    # The news beat: tell the story (what happened + why it moves the price)
    # when the LLM analysis is available; otherwise read the top headline as
    # before. The sentiment beat only exists alongside an analysis — with no
    # analysis the scene is dropped from the video entirely.
    analysis = brief.get("news_analysis") or {}
    stories = analysis.get("stories") or []
    if stories:
        s0 = stories[0]
        lines["news"] = f"Here's the big story. {s0['what_happened']}"
        if s0.get("price_impact"):
            lines["news"] += f" {s0['price_impact']}"
        if long and len(stories) > 1:
            lines["news"] += f" Also in the news: {stories[1]['what_happened']}"
    elif news:
        lines["news"] = f"And in the headlines: {news[0]['title']}."
        if long and len(news) > 1:
            lines["news"] += f" Plus, {news[1]['title']}."
    else:
        lines["news"] = ""

    if stories:
        label = analysis.get("sentiment_label") or "mixed"
        lines["sentiment"] = f"So what's the mood? {label}."
        if analysis.get("consumer_take"):
            lines["sentiment"] += f" {analysis['consumer_take']}"
    else:
        lines["sentiment"] = ""
```

Also update the module docstring's scene list comment in `build_narration` if present ("Returns {scene_id: text}" stays true — empty strings are already filtered by the final `return`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_learn_video.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/learn_brief.py backend/tests/test_learn_video.py
git commit -m "feat: quiz hook, big-story and sentiment narration beats"
```

---

### Task 4: Router threading + render cache bump

**Files:**
- Modify: `backend/app/routers/learn.py`
- Test: `backend/tests/test_learn_video.py` (append)

**Interfaces:**
- Consumes: `build_brief` keys from Task 2.
- Produces: `StockOfTheDayOut.news_analysis: dict` and `.price_history: dict`; render props gain `news_analysis` and `price_history`; `_CACHE_VERSION = "v6"`. The frontend (Tasks 5-8) reads `pick.news_analysis` / `pick.price_history` from the API and the same keys from render props.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_learn_video.py`:

```python
# --- router threading ------------------------------------------------------------

from app.routers import learn as learn_router


def test_to_out_threads_analysis_and_history(monkeypatch):
    brief = _brief()
    brief["price_history"] = {"points": [{"d": "2026-07-10", "c": 100.0}] * 2,
                              "events": []}
    monkeypatch.setattr(learn_router, "build_brief", lambda pick: brief)
    item = SimpleNamespace(
        ticker="MU", rank=1, price=100.0, screen_score=8.0, momentum_3mo=0.22,
        stance="bullish", confidence=0.7, summary="s", run_id="r1")
    out = learn_router._to_out(item, date(2026, 7, 11), enrich=True)
    assert out.news_analysis["stories"]
    assert out.price_history["points"]
    assert "sentiment" in out.captions


def test_cache_version_bumped():
    assert learn_router._CACHE_VERSION == "v6"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_learn_video.py -v`
Expected: FAIL — `StockOfTheDayOut` has no field `news_analysis`; `_CACHE_VERSION == "v5"`.

- [ ] **Step 3: Implement the router changes**

In `backend/app/routers/learn.py`:

3a. In `StockOfTheDayOut`, after the `captions` field add:

```python
    news_analysis: dict = {}  # LLM news deep-dive: stories + sentiment gauge
    price_history: dict = {}  # real 3-mo closes + news-event pins for the chart
```

3b. In `_to_out`, inside the `if enrich:` block after `out.captions = ...`:

```python
        out.news_analysis = brief["news_analysis"]
        out.price_history = brief["price_history"]
```

3c. In `_make_voiceover`, extend the reconstructed brief so the sentiment beat
survives the voiceover path:

```python
        brief = {
            "details": pick.details, "news": pick.news, "reasons": pick.reasons,
            "news_analysis": pick.news_analysis,
        }
```

3d. In `_run_render`, after `pick.reasons = brief["reasons"]` add:

```python
    pick.news_analysis = brief["news_analysis"]
    pick.price_history = brief["price_history"]
```

and in the `props` dict after `"reasons": pick.reasons,` add:

```python
        "news_analysis": pick.news_analysis,
        "price_history": pick.price_history,
```

3e. Bump the cache version:

```python
_CACHE_VERSION = "v6"  # v6: quiz hook, real chart, news deep-dive + sentiment
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests -q`
Expected: full suite PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/learn.py backend/tests/test_learn_video.py
git commit -m "feat: thread news analysis + price history through learn API and renders"
```

---

### Task 5: Frontend timeline — conditional sentiment scene + prop threading

**Files:**
- Modify: `frontend/src/video/StockVideo.jsx` (timeline exports + composition shell only — scenes come in Tasks 6-8)
- Modify: `frontend/remotion/Root.jsx`
- Modify: `frontend/src/components/LearnPanel.jsx`

**Interfaces:**
- Consumes: `pick.news_analysis` / `pick.price_history` from the API (Task 4).
- Produces: `sceneOrderFor(analysis) -> string[]`, `sceneDurations(sec, voice, analysis)`, `videoDurationInFrames(sec, voice, analysis)` — all backward compatible (missing `analysis` → sentiment scene omitted). Composition accepts `news_analysis = {}` and `price_history = {}` props. Tasks 6-8 rely on `T.sentiment` existing when analysis is present and on `sceneEl` keys matching the order array.

- [ ] **Step 1: Update the timeline machinery in `frontend/src/video/StockVideo.jsx`**

Replace the `SCENE_ORDER` const and the two comment lines above it:

```jsx
// Scene order (drives layout + the caption/audio track). "about" — what the
// company actually does — sits right after the ticker reveal; "sentiment"
// (the news-mood gauge) only exists when the LLM news analysis came back, so
// the order is computed per-video via sceneOrderFor().
const SCENE_ORDER = [
  "hook", "ticker", "about", "details", "momentum", "news", "sentiment",
  "why", "confidence", "outro",
];

const hasAnalysis = (analysis) =>
  Boolean(analysis && analysis.stories && analysis.stories.length);

export const sceneOrderFor = (analysis) =>
  hasAnalysis(analysis)
    ? SCENE_ORDER
    : SCENE_ORDER.filter((id) => id !== "sentiment");
```

Replace `MIN_BUDGET` with tightened 30s floors plus the sentiment scene (the
punchier pacing pass — scenes still stretch to fit narration, so nothing is
ever cut):

```jsx
const MIN_BUDGET = {
  30: {
    hook: 84, ticker: 88, about: 108, details: 100, momentum: 116,
    news: 128, sentiment: 104, why: 120, confidence: 90, outro: 62,
  },
  65: {
    hook: 110, ticker: 132, about: 190, details: 160, momentum: 170,
    news: 210, sentiment: 160, why: 210, confidence: 144, outro: 116,
  },
};
```

Update the three timeline functions to take the analysis:

```jsx
export function sceneDurations(sec = 30, voice = null, analysis = null) {
  const base = MIN_BUDGET[sec] ?? MIN_BUDGET[30];
  const out = {};
  for (const id of sceneOrderFor(analysis)) {
    let dur = base[id] ?? 120;
    const audio = clipFramesFor(voice, id);
    if (audio != null) dur = Math.max(dur, audio + LEAD_IN + TAIL_OUT);
    out[id] = dur;
  }
  return out;
}

export const timelineFor = (sec, voice = null, analysis = null) =>
  sceneDurations(sec, voice, analysis);

export const videoDurationInFrames = (sec, voice = null, analysis = null) =>
  Object.values(sceneDurations(sec, voice, analysis)).reduce((a, b) => a + b, 0);
```

- [ ] **Step 2: Update the composition shell in the same file**

In the `StockVideo` default export: add the two props and compute the order once —

```jsx
export default function StockVideo({
  /* …existing props unchanged… */
  news_analysis = {},
  price_history = {},
  captions = {},
  voice = null,
}) {
  const long = duration_sec >= 65;
  const order = sceneOrderFor(news_analysis);
  const T = sceneDurations(duration_sec, voice, news_analysis);
```

Then replace every `SCENE_ORDER` usage inside the component with `order`
(the `windows` walk, `captionWindows` map, and the final `{order.map((id) => …)}`
render loop). Add a placeholder entry to `sceneEl` so the file keeps compiling
until Task 8 lands the real scene:

```jsx
    sentiment: <Scene durationInFrames={T.sentiment ?? 120} />,
```

- [ ] **Step 3: Thread the new props through `frontend/remotion/Root.jsx`**

```jsx
        durationInFrames: videoDurationInFrames(
          props.duration_sec ?? 30,
          props.voice ?? null,
          props.news_analysis ?? null
        ),
```

- [ ] **Step 4: Thread through `frontend/src/components/LearnPanel.jsx`**

The frames calc:

```jsx
  const frames = videoDurationInFrames(
    duration,
    voiceOn ? voice : null,
    pick.news_analysis
  );
```

And in the `<Player inputProps={{…}}>` after `reasons: pick.reasons || [],`:

```jsx
              news_analysis: pick.news_analysis || {},
              price_history: pick.price_history || {},
```

- [ ] **Step 5: Verify the build**

Run: `cd frontend && npm run build`
Expected: build succeeds with no errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/video/StockVideo.jsx frontend/remotion/Root.jsx frontend/src/components/LearnPanel.jsx
git commit -m "feat: conditional sentiment scene timeline + new video props"
```

---

### Task 6: Quiz hook + ticker-reveal punch

**Files:**
- Modify: `frontend/src/video/StockVideo.jsx` (`HookScene`, `TickerScene`, new `Punch` block)

**Interfaces:**
- Consumes: `T` durations and existing `Scene`/`Pop`/`SlideIn`/`Kicker` helpers; `details` prop (sector, market_cap), `momentum_3mo`.
- Produces: `HookScene({ dateLabel, details, momentum3mo, duration })`, `Punch` animation helper (reused by Task 8's scenes if useful). `sceneEl.hook` gains new props.

- [ ] **Step 1: Add the `Punch` helper (after the `SlideIn` component)**

```jsx
// Zoom-punch: starts oversized-and-invisible, slams to rest with overshoot —
// the classic short-form "reveal" hit. Heavier spring than Pop on purpose.
function Punch({ delay = 0, children, style }) {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const s = spring({
    frame: frame - delay,
    fps,
    config: { damping: 10, stiffness: 210, mass: 0.7 },
  });
  return (
    <div
      style={{
        opacity: Math.min(1, s * 2),
        transform: `scale(${0.4 + s * 0.6})`,
        ...style,
      }}
    >
      {children}
    </div>
  );
}
```

- [ ] **Step 2: Replace `HookScene` with the quiz variant**

```jsx
// Short-form cold open: tease the pick as a guessing game. Three hint chips
// (sector / size / momentum) deal in over a blurred mystery ticker, and the
// answer lands in the next scene — a classic retention hook.
function capBucket(cap) {
  if (!cap || cap === "—") return null;
  if (cap.endsWith("T")) return "Trillion-dollar giant";
  if (cap.endsWith("B")) return "Multi-billion-dollar company";
  return "Smaller cap";
}

function HookScene({ dateLabel, details = {}, momentum3mo, duration = 90 }) {
  const frame = useCurrentFrame();
  const flash = interpolate(frame, [0, 6, 20], [0, 1, 0], {
    extrapolateRight: "clamp",
  });
  const pulse = 1 + Math.sin(frame / 6) * 0.04;
  const hints = [
    details.sector && { icon: "🏭", text: details.sector },
    capBucket(details.market_cap) && {
      icon: "💰",
      text: capBucket(details.market_cap),
    },
    momentum3mo != null && {
      icon: momentum3mo >= 0 ? "📈" : "📉",
      text: `${momentum3mo >= 0 ? "Up" : "Down"} ${Math.abs(
        momentum3mo * 100
      ).toFixed(0)}% in 3 months`,
    },
  ].filter(Boolean);

  return (
    <Scene durationInFrames={duration}>
      <AbsoluteFill style={{ background: `rgba(47,129,255,${flash * 0.18})` }} />
      <Pop>
        <div style={{ fontSize: 74, transform: `scale(${pulse})` }}>🤔</div>
      </Pop>
      <Pop delay={4}>
        <h1
          style={{
            fontSize: 108,
            fontWeight: 900,
            lineHeight: 1.04,
            margin: "20px 0 0",
            letterSpacing: -3,
          }}
        >
          CAN YOU GUESS
          <br />
          TODAY'S{" "}
          <span
            style={{
              background: `linear-gradient(90deg, ${C.accent}, ${C.green})`,
              WebkitBackgroundClip: "text",
              color: "transparent",
            }}
          >
            AI PICK?
          </span>
        </h1>
      </Pop>
      <Pop delay={12} from={40}>
        <div
          style={{
            marginTop: 40,
            padding: "18px 56px",
            borderRadius: 24,
            background: C.card,
            border: `1px solid ${C.cardBorder}`,
            fontSize: 100,
            fontWeight: 900,
            letterSpacing: 10,
            color: C.accentSoft,
            filter: "blur(14px)",
          }}
        >
          $????
        </div>
      </Pop>
      {hints.length > 0 && (
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            gap: 18,
            marginTop: 44,
          }}
        >
          {hints.map((h, i) => (
            <SlideIn key={h.text} delay={20 + i * 10} dir={i % 2 === 0 ? -1 : 1}>
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 16,
                  padding: "18px 30px",
                  borderRadius: 999,
                  background: C.card,
                  border: `1px solid ${C.cardBorder}`,
                  fontSize: 38,
                  fontWeight: 700,
                }}
              >
                <span style={{ fontSize: 40 }}>{h.icon}</span>
                <span>HINT {i + 1}: {h.text}</span>
              </div>
            </SlideIn>
          ))}
        </div>
      )}
      <Pop delay={40}>
        <p style={{ fontSize: 38, color: C.muted, marginTop: 42 }}>
          {dateLabel} · picked by AI agents
        </p>
      </Pop>
    </Scene>
  );
}
```

- [ ] **Step 3: Punch up `TickerScene`**

Change its `Kicker` line to `<Kicker>THE REVEAL</Kicker>`, wrap the `$ticker`
`<h1>` in `Punch` instead of `Pop` (`<Punch delay={4}>` replacing
`<Pop delay={6}>`), and remove the `Sparkline` block (the `<Pop delay={22} …>`
wrapper containing `<Sparkline …/>`) plus the whole `Sparkline` component
definition — the real chart scene (Task 7) replaces it. Keep the price
count-up and stance pill unchanged.

- [ ] **Step 4: Update `sceneEl.hook` in the composition**

```jsx
    hook: (
      <HookScene
        dateLabel={date_label}
        details={details}
        momentum3mo={momentum_3mo}
        duration={T.hook}
      />
    ),
```

Also delete the now-unused `momentum3mo` prop from `TickerScene`'s signature
and its `sceneEl.ticker` usage (it only fed the sparkline), keeping `name`.

- [ ] **Step 5: Verify the build**

Run: `cd frontend && npm run build`
Expected: build succeeds; `grep -n "Sparkline" frontend/src/video/StockVideo.jsx` returns nothing.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/video/StockVideo.jsx
git commit -m "feat: quiz-style hook scene and zoom-punch ticker reveal"
```

---

### Task 7: Real price chart scene with news pins

**Files:**
- Modify: `frontend/src/video/StockVideo.jsx` (new `PriceChartScene`; `sceneEl.momentum` selector)

**Interfaces:**
- Consumes: `price_history` prop `{points: [{d, c}], events: [{i, d}]}` (Task 2 shape), existing `MomentumScene` (kept as fallback), `AnimatedNumber`, `Kicker`, `Scene`.
- Produces: `PriceChartScene({ history, momentum3mo, screenScore, duration })`; scene id stays `momentum` so narration/voice keys are untouched.

- [ ] **Step 1: Add `PriceChartScene` (right above `MomentumScene`)**

```jsx
// The real 3-month price line (downsampled server-side), drawn on progressively
// with 📰 pins where the analyzed stories broke — so the "check out this chart"
// narration points at actual price action, not a decorative squiggle.
// MomentumScene (abstract bars) remains the fallback when history is missing.
function PriceChartScene({ history, momentum3mo, screenScore, duration = 150 }) {
  const frame = useCurrentFrame();
  const points = history.points;
  const events = history.events || [];
  const pctVal = (momentum3mo ?? 0) * 100;
  const up = pctVal >= 0;
  const color = up ? C.green : C.red;
  const W = 900;
  const H = 460;
  const closes = points.map((p) => p.c);
  const min = Math.min(...closes);
  const span = Math.max(...closes) - min || 1;
  const draw = interpolate(frame - 14, [0, 50], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });
  const shown = Math.max(2, Math.ceil(points.length * draw));
  const xy = (i) => [
    (i / (points.length - 1)) * W,
    H - ((points[i].c - min) / span) * (H - 40) - 20,
  ];
  const coords = points.slice(0, shown).map((_, i) => xy(i));
  const line = coords.map((c) => c.join(",")).join(" ");
  const area = `${line} ${coords[coords.length - 1][0]},${H} 0,${H}`;
  const [hx, hy] = coords[coords.length - 1];

  return (
    <Scene durationInFrames={duration}>
      <Kicker>THE LAST 3 MONTHS</Kicker>
      <Pop delay={4}>
        <div style={{ fontSize: 130, fontWeight: 900, color, margin: "10px 0 4px" }}>
          <AnimatedNumber
            value={pctVal}
            delay={10}
            format={(v) => `${v >= 0 ? "+" : ""}${v.toFixed(1)}%`}
          />
        </div>
      </Pop>
      <Pop delay={10} from={60}>
        <svg width={W} height={H} style={{ overflow: "visible", marginTop: 8 }}>
          <polygon points={area} fill={`${color}1d`} />
          <polyline
            points={line}
            fill="none"
            stroke={color}
            strokeWidth="7"
            strokeLinecap="round"
            strokeLinejoin="round"
            style={{ filter: `drop-shadow(0 0 18px ${color}88)` }}
          />
          <circle
            cx={hx}
            cy={hy}
            r="13"
            fill={color}
            style={{ filter: `drop-shadow(0 0 20px ${color})` }}
          />
          {events.map((e, idx) => {
            const i = Math.min(e.i ?? 0, points.length - 1);
            if (i >= shown) return null; // pin appears as the line reaches it
            const [x, y] = xy(i);
            return (
              <g key={idx}>
                <line
                  x1={x} y1={y} x2={x} y2={y - 52}
                  stroke={C.accentSoft} strokeWidth="3" strokeDasharray="4 6"
                />
                <text x={x} y={y - 62} fontSize="44" textAnchor="middle">
                  📰
                </text>
              </g>
            );
          })}
        </svg>
      </Pop>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          width: W,
          fontSize: 30,
          color: C.muted,
          marginTop: 10,
        }}
      >
        <span>{points[0].d}</span>
        <span>{points[points.length - 1].d}</span>
      </div>
      <Pop delay={44}>
        <p style={{ fontSize: 42, color: C.muted, marginTop: 40 }}>
          Technical screen score:{" "}
          <span style={{ color: C.text, fontWeight: 800 }}>
            {screenScore != null ? screenScore.toFixed(1) : "—"}
          </span>
        </p>
      </Pop>
    </Scene>
  );
}
```

- [ ] **Step 2: Select chart vs. bars in `sceneEl`**

Replace the `momentum:` entry (selection happens here, not inside a component,
so React hook order stays legal in both branches):

```jsx
    momentum:
      price_history.points && price_history.points.length > 1 ? (
        <PriceChartScene
          history={price_history}
          momentum3mo={momentum_3mo}
          screenScore={screen_score}
          duration={T.momentum}
        />
      ) : (
        <MomentumScene
          momentum3mo={momentum_3mo}
          screenScore={screen_score}
          duration={T.momentum}
        />
      ),
```

- [ ] **Step 3: Verify the build**

Run: `cd frontend && npm run build`
Expected: build succeeds.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/video/StockVideo.jsx
git commit -m "feat: real 3-month price chart scene with news-event pins"
```

---

### Task 8: Big-story scene + sentiment gauge scene

**Files:**
- Modify: `frontend/src/video/StockVideo.jsx` (new `BigStoryScene`, `SentimentScene`; `sceneEl.news` selector; replace the Task 5 sentiment placeholder)

**Interfaces:**
- Consumes: `news_analysis` prop (Task 1 shape), existing `NewsScene` (kept as fallback), `Scene`/`SlideIn`/`Pop`/`Kicker`, `spring`.
- Produces: `BigStoryScene({ analysis, long, duration })`, `SentimentScene({ analysis, duration })`.

- [ ] **Step 1: Add `BigStoryScene` (right above `NewsScene`)**

```jsx
// The news deep-dive: one story told in three beats — headline, what happened,
// and how it likely hits the price (colored by the story's sentiment). Falls
// back to NewsScene's plain headline cards when there's no LLM analysis.
function BigStoryScene({ analysis, long = false, duration = 150 }) {
  const stories = analysis.stories || [];
  const s0 = stories[0];
  const dir =
    s0.sentiment === "positive"
      ? { color: C.green, arrow: "▲" }
      : s0.sentiment === "negative"
      ? { color: C.red, arrow: "▼" }
      : { color: C.amber, arrow: "◆" };

  const card = {
    padding: "28px 34px",
    borderRadius: 24,
    background: C.card,
    border: `1px solid ${C.cardBorder}`,
    textAlign: "left",
    width: 920,
  };

  return (
    <Scene durationInFrames={duration}>
      <Kicker>THE BIG STORY</Kicker>
      <div style={{ display: "flex", flexDirection: "column", gap: 24, marginTop: 40 }}>
        <SlideIn delay={8} dir={-1}>
          <div style={{ ...card, display: "flex", gap: 22, alignItems: "flex-start" }}>
            <div style={{ fontSize: 46, lineHeight: 1 }}>📰</div>
            <div>
              <p style={{ fontSize: 44, fontWeight: 800, margin: 0, lineHeight: 1.24 }}>
                {s0.headline}
              </p>
              {s0.date && (
                <p style={{ fontSize: 28, color: C.muted, margin: "10px 0 0" }}>
                  {s0.date}
                </p>
              )}
            </div>
          </div>
        </SlideIn>
        <SlideIn delay={28} dir={1}>
          <div style={card}>
            <p style={{ fontSize: 32, color: C.accentSoft, fontWeight: 800, margin: 0, letterSpacing: 2 }}>
              WHAT HAPPENED
            </p>
            <p style={{ fontSize: 40, fontWeight: 600, margin: "10px 0 0", lineHeight: 1.32 }}>
              {s0.what_happened}
            </p>
          </div>
        </SlideIn>
        {s0.price_impact && (
          <SlideIn delay={48} dir={-1}>
            <div style={{ ...card, borderLeft: `10px solid ${dir.color}` }}>
              <p style={{ fontSize: 32, color: dir.color, fontWeight: 800, margin: 0, letterSpacing: 2 }}>
                PRICE IMPACT {dir.arrow}
              </p>
              <p style={{ fontSize: 40, fontWeight: 600, margin: "10px 0 0", lineHeight: 1.32 }}>
                {s0.price_impact}
              </p>
            </div>
          </SlideIn>
        )}
        {long && stories[1] && (
          <SlideIn delay={68} dir={1}>
            <div style={{ ...card, padding: "20px 30px" }}>
              <p style={{ fontSize: 32, color: C.muted, margin: 0, lineHeight: 1.3 }}>
                <span style={{ color: C.accentSoft, fontWeight: 800 }}>ALSO:</span>{" "}
                {stories[1].headline}
              </p>
            </div>
          </SlideIn>
        )}
      </div>
    </Scene>
  );
}
```

- [ ] **Step 2: Add `SentimentScene` (after `NewsScene`)**

```jsx
// News-mood gauge: a red→amber→green half-dial whose needle springs to the
// LLM's overall sentiment score, with the consumer/retail take underneath.
// Only mounted when an analysis exists (sceneOrderFor drops it otherwise).
function SentimentScene({ analysis, duration = 140 }) {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const score = Math.max(-1, Math.min(1, analysis.sentiment_score ?? 0));
  const s = spring({
    frame: frame - 12,
    fps,
    config: { damping: 12, stiffness: 70, mass: 1.1 },
  });
  // Needle sweeps from hard-bearish (-90°) to its target as the spring lands.
  const angle = interpolate(s, [0, 1], [-90, score * 90]);
  const scoreColor = score > 0.15 ? C.green : score < -0.15 ? C.red : C.amber;
  const R = 300;
  const CX = 330;
  const CY = 350;

  return (
    <Scene durationInFrames={duration}>
      <Kicker>NEWS SENTIMENT</Kicker>
      <Pop delay={6}>
        <svg width="660" height="410" style={{ marginTop: 26, overflow: "visible" }}>
          <defs>
            <linearGradient id="sentGrad" x1="0" y1="0" x2="1" y2="0">
              <stop offset="0%" stopColor={C.red} />
              <stop offset="50%" stopColor={C.amber} />
              <stop offset="100%" stopColor={C.green} />
            </linearGradient>
          </defs>
          <path
            d={`M ${CX - R} ${CY} A ${R} ${R} 0 0 1 ${CX + R} ${CY}`}
            fill="none"
            stroke="url(#sentGrad)"
            strokeWidth="42"
            strokeLinecap="round"
            opacity="0.92"
          />
          <g transform={`rotate(${angle} ${CX} ${CY})`}>
            <line
              x1={CX} y1={CY} x2={CX} y2={CY - R + 64}
              stroke={C.text} strokeWidth="11" strokeLinecap="round"
              style={{ filter: `drop-shadow(0 0 14px ${scoreColor})` }}
            />
            <circle cx={CX} cy={CY} r="22" fill={C.text} />
          </g>
          <text x={CX - R} y={CY + 52} fontSize="30" fill={C.muted} textAnchor="middle">
            BEARISH
          </text>
          <text x={CX + R} y={CY + 52} fontSize="30" fill={C.muted} textAnchor="middle">
            BULLISH
          </text>
        </svg>
      </Pop>
      <Pop delay={30}>
        <h2 style={{ fontSize: 76, fontWeight: 900, margin: "20px 0 0", color: scoreColor }}>
          {analysis.sentiment_label || "Mixed"}
        </h2>
      </Pop>
      {analysis.consumer_take && (
        <Pop delay={44} from={40}>
          <div
            style={{
              marginTop: 36,
              maxWidth: 900,
              padding: "26px 36px",
              borderRadius: 26,
              background: C.card,
              border: `1px solid ${C.cardBorder}`,
              fontSize: 40,
              lineHeight: 1.34,
              fontWeight: 600,
            }}
          >
            💬 {analysis.consumer_take}
          </div>
        </Pop>
      )}
    </Scene>
  );
}
```

- [ ] **Step 3: Wire both into `sceneEl`**

Replace the `news:` entry and the Task 5 `sentiment:` placeholder:

```jsx
    news:
      news_analysis.stories && news_analysis.stories.length ? (
        <BigStoryScene analysis={news_analysis} long={long} duration={T.news} />
      ) : (
        <NewsScene news={news} duration={T.news} />
      ),
    sentiment: (
      <SentimentScene analysis={news_analysis} duration={T.sentiment ?? 120} />
    ),
```

- [ ] **Step 4: Verify the build**

Run: `cd frontend && npm run build`
Expected: build succeeds.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/video/StockVideo.jsx
git commit -m "feat: big-story news scene and sentiment gauge scene"
```

---

### Task 9: Kinetic captions + emoji bursts + end-to-end verification

**Files:**
- Modify: `frontend/src/video/StockVideo.jsx` (`CaptionTrack`, new `EmojiBurst`, `PriceChartScene`/`ConfidenceScene` bursts)

**Interfaces:**
- Consumes: everything above.
- Produces: final v6 composition; verified preview + CLI render.

- [ ] **Step 1: Kinetic captions**

In `CaptionTrack`, compute the currently-lit word index and give it a pop.
Replace the `{words.map((w, i) => { … })}` block with:

```jsx
        {words.map((w, i) => {
          const lit = revealLocal >= i * per;
          const active = lit && revealLocal < (i + 1) * per;
          return (
            <span
              key={i}
              style={{
                opacity: lit ? 1 : 0.28,
                color: active ? C.accentSoft : lit ? C.text : C.muted,
                display: "inline-block",
                transform: active ? "scale(1.14)" : "scale(1)",
                transition: "opacity 0.1s, transform 0.1s, color 0.1s",
              }}
            >
              {w}
              {i < words.length - 1 ? " " : ""}
            </span>
          );
        })}
```

(The ` ` keeps the trailing space inside the inline-block span so word
spacing survives the transform.)

- [ ] **Step 2: Add `EmojiBurst` (after the `Punch` helper)**

```jsx
// A one-shot ring of emoji flying out from a point — cheap celebratory punch
// for the big numbers (momentum %, confidence %). Deterministic, no randomness.
function EmojiBurst({ emoji = "🔥", delay = 0, count = 6, top = "36%" }) {
  const frame = useCurrentFrame();
  const t = interpolate(frame - delay, [0, 42], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });
  if (t <= 0) return null;
  return (
    <AbsoluteFill style={{ pointerEvents: "none" }}>
      {Array.from({ length: count }).map((_, i) => {
        const a = (i / count) * Math.PI * 2 - Math.PI / 2;
        const r = t * (170 + (i % 3) * 70);
        return (
          <div
            key={i}
            style={{
              position: "absolute",
              left: `calc(50% + ${Math.cos(a) * r}px)`,
              top: `calc(${top} + ${Math.sin(a) * r * 0.7}px)`,
              fontSize: 56,
              opacity: 1 - t,
              transform: `scale(${0.6 + t * 0.8})`,
            }}
          >
            {emoji}
          </div>
        );
      })}
    </AbsoluteFill>
  );
}
```

- [ ] **Step 3: Fire the bursts**

In `PriceChartScene`, right after `<Kicker>THE LAST 3 MONTHS</Kicker>` add:

```jsx
      <EmojiBurst emoji={up ? "🔥" : "🥶"} delay={12} top="30%" />
```

In `ConfidenceScene`, right after its `<Kicker>` add:

```jsx
      <EmojiBurst emoji="🤖" delay={16} top="34%" />
```

In `MomentumScene` (the fallback), right after its `<Kicker>` add the same
line as PriceChartScene's (using its own `up` variable).

- [ ] **Step 4: Full verification**

```bash
cd backend && .venv/bin/python -m pytest tests -q
cd ../frontend && npm run build
```

Expected: backend suite PASS; frontend build succeeds.

Then a props-driven CLI render smoke test (no API keys needed — exercises the
new scenes with canned props including analysis + history):

```bash
cd frontend
cat > /tmp/v6-props.json <<'EOF'
{
  "ticker": "MU", "price": 100.5, "stance": "bullish", "confidence": 0.72,
  "momentum_3mo": 0.22, "screen_score": 8.2, "rank": 1,
  "summary": "Strong uptrend.", "date_label": "July 11, 2026",
  "duration_sec": 30,
  "details": {"name": "Micron", "sector": "Technology", "market_cap": "$120.00B",
              "pe_ratio": "24.1", "range_low": "$61.00", "range_high": "$110.00",
              "range_pos": 82, "about": "Micron makes memory and storage chips.",
              "industry": "Semiconductors", "employees": "48,000",
              "headquarters": "Boise, ID"},
  "news": [{"title": "Chipmaker beats on Q2 earnings", "source": "Reuters", "when": "1d ago"}],
  "reasons": [],
  "captions": {"hook": "Can you guess today's AI stock of the day?"},
  "news_analysis": {
    "stories": [{"headline": "Chipmaker beats on Q2 earnings",
                 "what_happened": "Revenue of $8.1B beat estimates, up 38% YoY.",
                 "price_impact": "Beats like this usually push the stock higher.",
                 "sentiment": "positive", "date": "2026-07-10"}],
    "sentiment_score": 0.6, "sentiment_label": "Leaning bullish",
    "consumer_take": "Retail investors are hyped about the AI demand story."
  },
  "price_history": {
    "points": [
      {"d": "2026-04-11", "c": 82.0}, {"d": "2026-04-25", "c": 85.5},
      {"d": "2026-05-09", "c": 84.0}, {"d": "2026-05-23", "c": 90.2},
      {"d": "2026-06-06", "c": 93.8}, {"d": "2026-06-20", "c": 97.1},
      {"d": "2026-07-04", "c": 96.0}, {"d": "2026-07-10", "c": 100.5}
    ],
    "events": [{"i": 7, "d": "2026-07-10"}]
  }
}
EOF
npx remotion render remotion/index.jsx StockOfTheDay /tmp/v6-smoke.mp4 --props=/tmp/v6-props.json --codec=h264
```

Expected: render completes; `/tmp/v6-smoke.mp4` exists and is non-trivial
(`ls -la /tmp/v6-smoke.mp4` shows > 1 MB). Optionally re-render with
`"news_analysis": {}` and `"price_history": {}` in the props to confirm the
fallback path (no sentiment scene, bars instead of chart) still renders.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/video/StockVideo.jsx
git commit -m "feat: kinetic captions and emoji bursts; verify v6 render end-to-end"
```

---

## Self-Review Notes

- **Spec coverage:** API budget → Tasks 1-2 (cache tests assert single calls); learn_news module → Task 1; brief keys + downsampling/pins → Task 2; narration beats incl. conditional sentiment → Task 3; router threading + v6 cache bump → Task 4; conditional scene order + Root/LearnPanel threading → Task 5; quiz hook + reveal punch (and fake-sparkline removal) → Task 6; real chart with pins + bars fallback → Task 7; big story + gauge with headline-card fallback → Task 8; pacing (tight floors in Task 5's MIN_BUDGET, kinetic captions, emoji bursts, zoom punch) → Tasks 5/6/9; error handling → fallback branches tested in Task 2 and exercised in Task 9's fallback render.
- **Type consistency:** `analyze_news` signature matches its Task 2 call site; `price_history` events use `{i, d}` in both backend and `PriceChartScene`; `sceneOrderFor/sceneDurations/videoDurationInFrames` third arg consistent across StockVideo/Root/LearnPanel; scene ids match narration keys.
- **Known simplification:** the sentiment scene's presence keys off `news_analysis.stories` everywhere (order, narration, sceneEl), so preview, voiceover, and render can never disagree about the timeline.
