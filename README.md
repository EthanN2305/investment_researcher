# AI Investment Research Analyst

A multi-agent AI system that researches a stock and produces an **explainable,
sourced, confidence-scored** research report. This repo currently implements
**Phase 2**: specialized agents coordinated by a LangGraph planner that can
pause mid-run to ask the user clarifying questions.

> Informational research tool — **not** licensed investment advice. Every claim
> shows its evidence and source.

## What Phase 2 does

Enter a ticker → a **Planner** decides which agents to run (quick check vs
deep dive) and pauses to ask if anything is ambiguous (share class, lens) →
specialist agents run in parallel, streaming live progress to the UI → a
**Recommendation Agent** synthesizes their structured claims into a final
stance → the React UI renders the report grouped by contributing agent.

```
frontend ──POST /research──▶ planner (LangGraph, can interrupt ↔ user)
   ▲                            ├──▶ News Agent        (NewsAPI + Claude)
   │ SSE: per-agent progress,   ├──▶ Financial Agent   (SEC EDGAR 10-K facts)
   │ questions, final report    ├──▶ Technical Agent   (SMA/RSI/trend, yfinance)
   └────────────────────────────┤    └─▶ Valuation Agent (market + EDGAR ratios)
                                └──▶ Recommendation Agent (structured claims only)
```

Key properties:

- **Same claim contract as Phase 1** — every agent emits
  `{claim, evidence, source, confidence}`; the Recommendation Agent consumes
  only these structured claims, never free text.
- **Failure isolation** — one agent failing (e.g. news API down) becomes a
  flag on the report; the run continues.
- **Human-in-the-loop** — LangGraph `interrupt()` + checkpointing pause the
  run for clarifying questions ("GOOG has two share classes — which one?",
  "growth or value lens?") and resume with the answer.

## Project layout

```
backend/
  app/
    main.py         FastAPI: POST /research, SSE /research/{run}/events,
                    POST /research/{run}/answer, /health
    runs.py         run lifecycle: worker threads, interrupt/resume, SSE
    graph/
      build.py      LangGraph topology (planner → fan-out → gather → recommend)
      planner.py    plan choice + clarifying-question interrupts
      state.py      shared graph state + reducers, quick/deep plans
      events.py     per-run progress event history (SSE source)
    agents/         news, financials, valuation, technicals, recommend
    models.py       Claim / AgentReport / FinalReport contracts
    pipeline.py     Phase-1 single pipeline (kept for reference/tests)
    tools/          swappable providers: yfinance, NewsAPI, SEC EDGAR,
                    price history, Anthropic (structured output)
  tests/            test_smoke (Phase 1), test_phase2 (graph), test_e2e_api (SSE)
frontend/
  src/App.jsx                    run lifecycle + SSE handling
  src/components/AgentProgress   live per-agent status board
  src/components/QuestionCard    planner's clarifying-question UI
  src/components/ReportView      report grouped by agent + recommendation
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
[NewsAPI (free tier)](https://newsapi.org/register). SEC EDGAR needs no key
(set `SEC_USER_AGENT` contact info in `.env` per their fair-access policy).

### 2. Frontend

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173  (proxies /research to :8000)
```

Open http://localhost:5173, enter a ticker, pick a depth (or "Let the planner
ask" to see the clarifying-question flow). Try `GOOG` to see the share-class
question.

## Guardrails (active since Phase 1)

- Every claim carries evidence + source + confidence.
- Output is framed as research/education, not personalized advice.
- Missing/failed data is surfaced as `flags`, never silently filled.
- Each report is appended to `backend/recommendations_log.jsonl` so
  recommendations can be checked against outcomes later.

## Tests

```bash
cd backend
python -m tests.test_smoke      # Phase 1 contract + pipeline
python -m tests.test_phase2     # planner routing, interrupts, failure isolation
python -m tests.test_e2e_api    # full HTTP run: SSE + question/answer flow
```

No API keys needed — all tools are faked.

## Roadmap

Phase 1 single pipeline ✅ → **Phase 2 specialized agents + LangGraph planner ✅
(this)** → Phase 3 portfolios/personalization → Phase 4
watchlists/alerts/confidence UI → Phase 5 adaptive memory. See `brainstorm/`
for full phase specs.
