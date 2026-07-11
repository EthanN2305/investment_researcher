# Learn-tab video v6 — interactive short + news deep-dive

**Date:** 2026-07-11
**Status:** Approved (user), with constraint: *be very efficient with API usage*.

## Goal

Make the Learn-tab "Stock of the Day" short (Remotion, 1080×1920, 30s/65s)
feel like a native TikTok/Shorts production, and replace the bare headline
cards with a real news analysis: what happened, how it likely affects the
price, and what the mood (consumer/retail sentiment) is — all grounded in
fetched articles, never fabricated.

## User decisions

- Engagement upgrades: **all four** — real price chart, quiz hook, punchier
  pacing/motion, sentiment meter scene.
- News depth: **one structured LLM call** (Anthropic, forced-tool-call
  pattern already used in `app/tools/llm.py`).
- Consumer sentiment: **news-derived** (no new social integrations).
- **API efficiency is a hard requirement** (see Budget below).

## API budget (hard requirement)

Per (ticker, day), across any number of tab loads, shuffles back to the same
ticker, voiceover builds, and renders:

- **1 NewsAPI call** — one `get_news(ticker, limit=8)` fetch shared by the
  headline-card fallback AND the LLM analysis. `learn_brief.recent_news` must
  not fetch separately; `build_brief` fetches once and passes items to both.
- **≤1 Anthropic call** — `learn_news.analyze_news` result cached in-process
  keyed `(ticker, date)` (analysis of a day's news doesn't go stale within
  the day). Failures cache a short-TTL negative result so a downed provider
  isn't hammered on every page view. `max_tokens` kept small (~700); input is
  only titles + descriptions of ≤8 articles.
- **1 yfinance history call** — `YFinancePriceHistory.get_history(ticker,
  "3mo")` wrapped in the same (ticker, day) cache. No new quoteSummary calls
  (market data already cached 5 min in `market_data.py`).

The whole brief (details + news + analysis + history) is memoized per
(ticker, date) so `/learn/stock-of-the-day`, `/learn/shuffle`,
`/learn/voiceover`, and `/learn/render` all share one set of upstream calls.

## Backend

### New: `backend/app/learn_news.py`

`analyze_news(ticker, name, price, momentum_3mo, news_items) -> dict | None`

- Input: the already-fetched `NewsItem`s (titles + descriptions + dates).
  **No fetching inside this module.**
- One Anthropic call using the forced-tool-call pattern (`tool_choice`),
  system prompt reusing the grounding rules from `claims_from_news` (judge
  substance not scary words; weight recent articles; never invent figures;
  skip promotional/listicle content).
- Tool schema `emit_video_news`:
  - `stories` (1–2 items): `headline` (≤90 chars), `what_happened`
    (≤200 chars, plain English), `price_impact` (≤180 chars, how it likely
    moves the stock and why), `sentiment` (`positive|neutral|negative`),
    `date` (ISO date of the source article, from the supplied list only).
  - `sentiment_score`: number −1…1 (overall news mood for the stock).
  - `sentiment_label`: ≤24 chars, e.g. "Leaning bullish".
  - `consumer_take`: ≤160 chars — what retail investors/consumers are likely
    feeling, derived only from the coverage.
- Returns `None` on any failure (no key, timeout, bad output). Never raises.
- In-process cache: `(ticker, date) -> result`, including a negative-result
  entry with a ~10-minute TTL so failures retry occasionally but not per
  request.

### `backend/app/learn_brief.py`

- `build_brief` becomes the single fetch point, memoized per (ticker, date):
  fetches news once (limit 8), builds headline cards from it, calls
  `analyze_news` with the same items, and fetches 3-month price history.
- New brief keys:
  - `news_analysis`: the dict above (or `{}`).
  - `price_history`: `{points: [{d, c}, …] (≤60 downsampled closes),
    events: [{i, label}]}` — each analyzed story's date mapped to the nearest
    point index so the chart can pin 📰 markers. `{}` when history fails.
- `build_narration` updates:
  - `hook`: quiz tease — "Can you guess today's AI stock of the day? Here's
    a hint…" (hints spoken briefly at 65s).
  - `news`: narrates story 1's `what_happened` + `price_impact` (65s adds
    story 2) instead of reading a headline. Falls back to the old headline
    line when analysis is missing.
  - New `sentiment` beat: sentiment label + consumer take. Only emitted when
    analysis exists (missing key → scene and audio skipped).
  - `momentum` beat retitled to narrate the real chart ("Here's the last
    three months…").

### `backend/app/routers/learn.py`

- `StockOfTheDayOut` gains `news_analysis: dict = {}` and
  `price_history: dict = {}`; threaded through `_to_out(enrich=True)` and the
  render props in `_run_render`.
- `_CACHE_VERSION` → `"v6"` (composition + narration changed).

## Frontend — `frontend/src/video/StockVideo.jsx`

Scene order: `hook(quiz) → ticker(reveal) → about → details → chart →
news(big story) → sentiment → why → confidence → outro`.
`SCENE_ORDER` is filtered at runtime: `sentiment` drops out when there's no
analysis (duration math already walks the order, so timing stays exact).

- **HookScene → quiz**: "Can you guess today's pick?" + three hint chips
  dealing in (sector, market-cap bucket, "up X% in 3 months" — all from
  existing props), building into the ticker reveal.
- **TickerScene**: zoom-punch reveal (scale overshoot + flash), keeps price
  count-up and stance pill; decorative fake sparkline removed.
- **PriceChartScene** (replaces MomentumScene's abstract bars): animated
  path-draw of real closes, gradient area, big ±% badge counting up, 📰 pins
  popping at `events` indices. Falls back to the current bars when
  `price_history` is empty.
- **NewsScene → big story**: story 1 headline card, then "WHAT HAPPENED" and
  "PRICE IMPACT" lines revealing in sequence, with directional color/arrow
  from `sentiment`. 65s shows story 2 compactly. No analysis → current
  headline-card list; no news at all → current "flagged on technicals" copy.
- **SentimentScene** (new): semicircular red→amber→green gauge, needle
  springs to `sentiment_score`, `sentiment_label` headline, `consumer_take`
  line beneath.
- **Pacing pass**: zoom-punch transitions on scene entry, tighter 30s floors
  (`MIN_BUDGET`), kinetic captions (active word pops in accent color/scale),
  emoji bursts on the momentum % and confidence % counters. Narration-driven
  stretching is unchanged — audio is never cut.

## Error handling

Every new datum is optional; every scene keeps today's behavior as its
fallback. `analyze_news` and history fetches can't raise out of
`build_brief`. A render can never fail because of a missing NEWSAPI key,
missing ANTHROPIC key, or a throttled yfinance.

## Testing

- pytest (`backend/tests/`): `learn_news` with a mocked Anthropic client —
  output shape/caps, cache hit (client called once for two calls same day),
  failure → `None` + negative-result caching; `build_brief` single-fetch
  behavior (news tool called once); narration beats with and without
  analysis.
- Frontend: in-app `<Player>` preview + one CLI render smoke test; existing
  `npm run build` must pass.
