# AI Investment Research Analyst — Project Brief

## Purpose
A multi-agent AI system that researches a stock (or a user's portfolio) by gathering
live market data, fundamentals, news, and technicals, reasoning over the evidence,
asking for missing information when needed, and producing an explainable
recommendation with sources and a confidence score.

This is an **informational research tool**, not a licensed investment advisor. Every
output should show its evidence and sources.

---

## Tech Stack
- **Frontend:** React
- **Backend / Orchestration:** Python, FastAPI, LangGraph
- **Agent-to-agent state:** LangGraph graph state (typed, not free text)
- **Streaming:** Server-Sent Events or WebSockets from FastAPI to React, so the user
  sees each agent's progress live ("Fetching earnings...", "Reading news...", etc.)
- **Data layer:** a thin "tool" abstraction per data source, so providers can be
  swapped without touching agent logic

> Node.js is intentionally left out of Phase 1–2. Add it later only if a concrete need
> arises (e.g., a separate auth service, a BFF for a mobile client). FastAPI can stream
> directly to React.

---

## Core Design Principle: Structured Agent Output

Every agent — from Phase 1 onward — returns a structured object, not a paragraph:

```json
{
  "agent": "financial_statement_agent",
  "claims": [
    {
      "claim": "Revenue grew 12% YoY in Q2",
      "evidence": "Q2 10-Q, total revenue $X vs $Y prior year",
      "source": "SEC EDGAR 10-Q filing, [url]",
      "confidence": 0.9
    }
  ],
  "flags": ["missing_guidance_data"]
}
```

The Recommendation Agent composes these structured claims from all agents into a
final report — it never has to re-parse prose. This is what makes "explainable
reasoning with confidence scores" (Phase 4) possible without a rewrite.

---

## Agents

| Agent | Responsibility | Key data sources |
|---|---|---|
| **Planner / Orchestrator** | Decides which agents to run, in what order, handles retries and missing-data follow-ups | — |
| **Market Data Agent** | Live price, volume, market cap | Yahoo Finance (`yfinance`), swappable to Alpha Vantage / Polygon.io |
| **Financial Statement Agent** | Revenue, margins, debt, filings analysis | SEC EDGAR (full-text search + XBRL company facts API) |
| **News Agent** | Recent news, sentiment, catalysts | NewsAPI / Benzinga / RSS (note licensing costs) |
| **Economic Agent** | Macro context: rates, sector conditions | FRED API, sector ETF data |
| **Valuation Agent** | P/E, P/S, DCF-style comparisons | Derived from Market Data + Financial Statement agents |
| **Technical Analysis Agent** | Moving averages, RSI, trend signals | Price history via Market Data Agent |
| **Competitor Agent** | Peer comparison | Same sources, applied to peer tickers |
| **Recommendation Agent** | Synthesizes all claims into a final, sourced, confidence-scored report | Consumes structured output from all above |
| **Portfolio Manager Agent** *(Phase 3+)* | Personalizes against the user's actual holdings and stated preferences | User profile/portfolio store |

---

## Phased Roadmap

**Phase 1 — Single-ticker research report**
User enters a ticker → one pipeline fetches live price data + recent news → LLM
produces a sourced research report. No multi-agent orchestration yet; this phase
proves the data pipeline and the structured-output/report format.

**Phase 2 — Specialized agents + planner**
Split Phase 1's pipeline into distinct agents (news, financials, valuation,
technicals) coordinated by a Planner via LangGraph. Planner can ask the user for
missing info (e.g., "Do you want a value or growth lens on this?").

**Phase 3 — Portfolios and personalization**
Users create accounts, store portfolios and preferences. Portfolio Manager Agent
personalizes recommendations against actual holdings and stated risk tolerance.

**Phase 4 — Watchlists, alerts, daily summaries, confidence scores**
Daily AI summaries, watchlist alerts, and full display of the confidence-scored,
evidence-linked reasoning chain in the UI.

**Phase 5 — Adaptive memory**
System tracks how the user responds to past recommendations (dismissed, acted on,
disagreed) and adapts future reasoning to their demonstrated investment style.

---

## Guardrails (apply from Phase 1)
- Always show sources for every claim.
- Frame output as research/education, not personalized financial advice.
- Flag missing or stale data rather than filling gaps silently.
- Log recommendations somewhere so they can be checked against outcomes later
  (even an informal running log is enough to start).

---

## Starter Prompt for Phase 1 Build

Use this to kick off a build session with an AI coding assistant:

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
