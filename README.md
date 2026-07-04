# AI Investment Research Analyst

A multi-agent AI system that researches a stock and produces an **explainable,
sourced, confidence-scored** research report. This repo currently implements
**Phase 4**: watchlists, scheduled daily summaries, configurable alerts with
in-app/email notifications, and a fully surfaced explainable-reasoning UI —
on top of Phase 3's accounts/portfolios and the Phase 2 LangGraph planner.

> Informational research tool — **not** licensed investment advice. Every claim
> shows its evidence and source.

## What Phase 4 adds

- **Watchlists** — track tickers independently of your holdings
  (`/watchlist` CRUD + a dedicated Watchlist tab).
- **Scheduled daily summaries** — an in-process APScheduler job (first
  background job in the project) runs the full agent pipeline once daily for
  every watched/held ticker and **stores** the structured report
  (`stored_reports` table), so the Daily Feed reads instantly without
  re-running agents. `POST /summaries/run` triggers the identical code path on
  demand ("Run now" button). Set `DAILY_SUMMARY_HOUR_UTC` /
  `DAILY_SUMMARY_MINUTE_UTC` to change the schedule; `SCHEDULER_ENABLED=false`
  disables it.
- **Alerts** — per-ticker rules: price move beyond ±X%, a *new*
  high-confidence claim (≥ threshold), or *new* negative news (keyword
  heuristic). Evaluated after each summary run, diffed against the previous
  stored report so the same claim never re-fires. In-app notifications
  (header bell) always; per-rule **email** as a stretch (SMTP via `SMTP_*`
  env vars, console fallback in dev).
- **Email digest** — opt in to have the daily feed emailed on your own
  cadence: every day, a chosen weekday, or the 1st of each month. Sent
  automatically right after the daily sweep (deduped per day), with a
  "Send test email" preview button. Configured in the Daily Feed tab.
- **Explainable reasoning UI** — claims are collapsed to headline +
  color-coded confidence bar and expand to show evidence and source, grouped
  by contributing agent. The Recommendation Agent's overall confidence is now
  **derived** from the underlying agents — weighted by claim volume and source
  reliability, penalized for failed agents and cross-agent disagreement, then
  blended with the synthesis model's self-estimate — and the report shows the
  per-agent breakdown plus a plain-English rationale ("Why 72% confident?").

## What Phase 3 added

Sign up → enter your holdings (ticker, quantity, cost basis) and stated
preferences (risk tolerance, sector interests, growth/value lean, time
horizon) → research any ticker while logged in and a **Portfolio Manager
Agent** joins the run, emitting the same structured claims about *fit*:
concentration risk, sector overlap/diversification, and mismatches with your
stated preferences. Its claims feed the Recommendation Agent alongside the
general analysis, and the report shows a distinct **"How this fits your
portfolio"** section. Anonymous runs behave exactly as in Phase 2.

- **Auth:** email/password (bcrypt) + JWT bearer tokens
- **Storage:** SQLite via SQLAlchemy 2.0 (`DATABASE_URL` swaps in Postgres)
- **Explicit preferences only** — nothing inferred (that's Phase 5)

## How a run works (Phase 2 core)

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
                                │        └─▶ Portfolio Manager Agent (logged in)
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
    main.py         FastAPI: POST /research (optionally personalized),
                    SSE /research/{run}/events, /research/{run}/answer, /health
    runs.py         run lifecycle: worker threads, interrupt/resume, SSE
    db.py           SQLAlchemy engine/session (SQLite by default)
    db_models.py    User / Holding / Preferences + WatchlistItem / StoredReport /
                    AlertRule / Notification ORM tables
    auth.py         bcrypt hashing, JWT create/verify, auth dependencies
    scheduler.py    APScheduler daily-summary job (in-process, cron)
    summaries.py    headless pipeline runs → stored reports (job + run-now)
    alerts_engine.py alert condition evaluation (price move, new claims, news)
    notify.py       in-app notification rows + SMTP email (console fallback)
    digest.py       email digest: cadence check (daily/weekly/monthly) + body
    routers/
      auth.py       POST /auth/signup, /auth/login, GET /auth/me
      portfolio.py  CRUD: /portfolio (holdings), /preferences
      watchlist.py  CRUD: /watchlist
      summaries.py  GET /summaries (feed), GET /summaries/{id},
                    POST /summaries/run (job) + GET /summaries/run/{job_id}
      alerts.py     CRUD: /alerts (rules), /notifications (+ read endpoints)
      digest.py     GET/PUT /digest (email cadence), POST /digest/send-now
    graph/
      build.py      LangGraph topology (planner → fan-out → gather →
                    valuation → portfolio → recommend)
      planner.py    plan choice + clarifying-question interrupts
      state.py      shared graph state + reducers, quick/deep plans
      events.py     per-run progress event history (SSE source)
    agents/         news, financials, valuation, technicals, portfolio, recommend
    models.py       Claim / AgentReport / FinalReport / PortfolioContext contracts
    pipeline.py     Phase-1 single pipeline (kept for reference/tests)
    tools/          swappable providers: yfinance, NewsAPI, SEC EDGAR,
                    price history, Anthropic (structured output)
  tests/            test_smoke (Phase 1), test_phase2 (graph), test_e2e_api (SSE),
                    test_phase3 (auth, CRUD, portfolio agent, personalized runs),
                    test_phase4 (watchlist, summaries, alerts, derived confidence)
frontend/
  src/App.jsx                     run lifecycle + SSE + auth state + tabs
  src/components/AgentProgress    live per-agent status board
  src/components/QuestionCard     planner's clarifying-question UI
  src/components/ReportView       report grouped by agent + confidence breakdown
  src/components/ClaimCard        expandable claim: headline → evidence + source
  src/components/AuthForm         sign-in / create-account
  src/components/PortfolioPanel   holdings entry/edit table
  src/components/PreferencesForm  risk / sectors / lean / horizon
  src/components/WatchlistPanel   watched tickers (add/remove/research-now)
  src/components/SummaryFeed      daily summary dashboard + run-now progress bar
  src/components/DigestSettings   email digest cadence (daily/weekly/monthly)
  src/components/AlertsConfig     alert rule configuration screen
  src/components/NotificationBell header bell: unread badge + dropdown
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

Phase 3 storage needs no setup: a SQLite file (`backend/investment.db`) is
created on first boot. Set `DATABASE_URL` in `.env` to use Postgres instead,
and set a real `JWT_SECRET` for anything beyond local development.

### 2. Frontend

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173  (proxies /research to :8000)
```

Open http://localhost:5173, enter a ticker, pick a depth (or "Let the planner
ask" to see the clarifying-question flow). Try `GOOG` to see the share-class
question. To see personalization: **My Portfolio → create an account → add
holdings + preferences → run a research query** — the report gains a
"How this fits your portfolio" section.

To try Phase 4 end-to-end: **Watchlist → add tickers → Alerts → add a rule →
Daily Feed → "Run now"**. Stored summaries appear in the feed (expandable to
the full report), and any fired alerts show up in the header bell. The same
job runs automatically at `DAILY_SUMMARY_HOUR_UTC` (default 13:30 UTC).

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
python -m pytest tests/test_phase3.py  # auth, CRUD, portfolio agent, personalization
python -m pytest tests/test_phase4.py  # watchlist, summaries job, alerts, confidence
```

No API keys needed — all tools are faked.

## Roadmap

Phase 1 single pipeline ✅ → Phase 2 specialized agents + LangGraph planner ✅
→ Phase 3 portfolios/personalization ✅ → **Phase 4
watchlists/alerts/confidence UI ✅ (this)** → Phase 5 adaptive memory. See
`brainstorm/` for full phase specs.
