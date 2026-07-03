# Phase 1 — Single-Ticker Research Report

## Goal
User enters a stock ticker and receives an AI-generated research report grounded
in live market data and recent news. No multi-agent orchestration yet — this phase
proves the data pipeline and the structured-output report format that later phases
build on.

## Scope
- No user accounts, no persistence. Stateless per request.
- One backend pipeline (not yet split into separate agents).
- Frontend: single input, loading state, report view.

## Requirements
- FastAPI endpoint (e.g. `POST /research/{ticker}`) that:
  1. Fetches price/fundamentals data via `yfinance` (or chosen equivalent).
  2. Fetches recent news for the ticker via a news API or RSS source.
  3. Passes both into an LLM call that produces a research report.
- The LLM's output must be **structured JSON**, not a single free-text blob:
  ```json
  {
    "ticker": "AAPL",
    "claims": [
      {
        "claim": "string",
        "evidence": "string",
        "source": "string (url or filing name)",
        "confidence": 0.0
      }
    ],
    "summary": "string"
  }
  ```
  This is required even though only one "agent" exists right now — Phase 2 depends
  on every agent already speaking this format.
- Data-fetching functions should be written as swappable interfaces (e.g.
  `get_market_data(ticker)`, `get_news(ticker)`), not inlined API calls, so
  providers can be changed later without touching report logic.
- React frontend:
  - Ticker input + submit
  - Loading indicator while the backend runs
  - Report view that renders the structured claims list with sources, plus the
    summary
- Handle basic failure cases gracefully: invalid ticker, no news found, API
  timeout — show a clear message rather than a blank/broken report.

## Explicitly out of scope for this phase
- Multiple agents or a planner
- User accounts, portfolios, watchlists
- Technical indicators, valuation ratios, competitor comparison
- Memory or personalization

## Starter Prompt

> Build Phase 1 of an AI investment research tool: a FastAPI backend and React
> frontend where a user enters a stock ticker and receives an AI-generated research
> report grounded in live market data and recent news.
>
> Requirements:
> - FastAPI endpoint that takes a ticker, fetches price/fundamentals data (via
>   `yfinance`) and recent news (via [chosen news API]), and calls an LLM to produce
>   a report.
> - The LLM's output must be structured JSON (claim, evidence, source, confidence
>   per point) — not a single free-text blob — so future phases can compose it with
>   other agents.
> - React frontend: ticker input, loading state, and a report view that renders the
>   structured claims with their sources.
> - Design the data-fetching functions as swappable "tools" (interfaces), not
>   hardcoded calls, so providers can change later without touching report logic.
> - No user accounts or persistence yet — this phase is stateless per request.
