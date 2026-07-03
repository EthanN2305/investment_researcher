# AI Investment Research Analyst

A multi-agent AI system that researches a stock and produces an **explainable,
sourced, confidence-scored** research report. This repo currently implements
**Phase 1**: a single-ticker pipeline that proves the data plumbing and the
structured-output report format the later phases build on.

> Informational research tool — **not** licensed investment advice. Every claim
> shows its evidence and source.

## What Phase 1 does

Enter a ticker → the backend fetches live price/fundamentals (`yfinance`) and
recent news (NewsAPI) → Claude synthesizes a **structured JSON** report of
sourced, confidence-scored claims → the React UI renders it.

```
frontend (React/Vite)  ──POST /research/{ticker}──▶  backend (FastAPI)
                                                        ├─ MarketDataProvider  (yfinance)
                                                        ├─ NewsProvider        (NewsAPI)
                                                        └─ LLMProvider         (Anthropic)
```

Data sources and the LLM are behind **swappable Protocol interfaces**
(`backend/app/tools/base.py`), so Phase 2 can split them into real agents and
swap providers without touching report logic.

## Project layout

```
backend/
  app/
    main.py         FastAPI app + POST /research/{ticker}, /health
    pipeline.py     Phase-1 orchestration (fetch → synthesize → assemble)
    models.py       Claim / ResearchReport contract + tool payloads
    config.py       env settings
    logstore.py     append-only recommendations log (guardrail)
    tools/
      base.py       Protocol interfaces + ToolError
      market_data.py  yfinance impl
      news.py         NewsAPI impl
      llm.py          Anthropic impl (structured output via forced tool call)
  tests/test_smoke.py   no-key smoke tests
  requirements.txt
  .env.example
frontend/
  src/App.jsx, api.js, components/{ReportView,ClaimCard}.jsx, styles.css
```

## Quickstart

### 1. Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env      # then fill in ANTHROPIC_API_KEY and NEWSAPI_KEY
uvicorn app.main:app --reload --port 8000
```

Get keys: [Anthropic](https://console.anthropic.com/) ·
[NewsAPI (free tier)](https://newsapi.org/register)

Check it's up: `curl -X POST http://localhost:8000/research/AAPL`

### 2. Frontend

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173  (proxies /research to :8000)
```

Open http://localhost:5173 and enter a ticker.

## Guardrails (active from Phase 1)

- Every claim carries evidence + source + confidence.
- Output is framed as research/education, not personalized advice.
- Missing/stale data is surfaced as `flags`, never silently filled.
- Each report is appended to `backend/recommendations_log.jsonl` so
  recommendations can be checked against outcomes later.

## Tests

```bash
cd backend && python -m tests.test_smoke
```

No API keys needed — uses fakes to verify the contract, pipeline, graceful
degradation, and endpoint wiring.

## Roadmap

Phase 1 (this) → Phase 2 specialized agents + LangGraph planner → Phase 3
portfolios/personalization → Phase 4 watchlists/alerts/confidence UI →
Phase 5 adaptive memory. See `brainstorm/` for full phase specs.
