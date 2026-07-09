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
  background job in the project) runs the agent pipeline once daily for
  every watched/held ticker and **stores** the structured report
  (`stored_reports` table), so the Daily Feed reads instantly without
  re-running agents. The sweep computes each distinct ticker's
  non-personalized report **once** and reuses it across users, layering only a
  cheap per-user portfolio-fit re-synthesis on top — so LLM cost scales with
  distinct tickers, not users × tickers. `POST /summaries/run` triggers the
  identical code path on demand ("Run now" button). Set `DAILY_SUMMARY_HOUR_UTC`
  / `DAILY_SUMMARY_MINUTE_UTC` to change the schedule; `SCHEDULER_ENABLED=false`
  disables it. **The scheduler is in-process, so it runs once per uvicorn
  worker — run the API with a single worker (or move the job to a dedicated
  scheduler process) so the sweep doesn't run N times.**
- **Alerts** — per-ticker rules: price move beyond ±X%, a *new*
  high-confidence claim (≥ threshold), or *new* negative news (driven by the
  news agent's LLM-emitted `sentiment`, with a keyword heuristic as fallback).
  Evaluated after each summary run, diffed against the previous
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

## Confidence calibration — closing the loop

The derived confidence above is only as good as its hand-tuned weights until
it's checked against reality. This closes that loop: it scores past
recommendations against realized outcomes and, once enough have resolved,
replaces the hand-tuned number with an empirically fitted one.

**Methodology**

- **Snapshot.** When a daily-summary report is stored, a *pending*
  `report_outcomes` row records the stance, the shown confidence, the
  *uncalibrated* `prior_confidence`, and the derivation features (coverage,
  disagreement spread, LLM self-estimate) at prediction time.
- **Resolve.** A scheduled backfill (`CALIBRATION_BACKFILL_HOURS`, default 6h)
  resolves each pending row once its horizon has elapsed: it compares the
  ticker's forward total return to a benchmark (`CALIBRATION_BENCHMARK`,
  default `SPY`) over `CALIBRATION_HORIZON_DAYS` (default 30) **trading** days,
  using a strictly forward price window (no lookahead). A `bullish` call is
  correct if it beat the benchmark by more than a ±band
  (`CALIBRATION_BAND_PCT`, default 2%), `bearish` if it trailed by more,
  `neutral` if it stayed within the band.
- **Measure.** From the resolved (predicted, correct) pairs it computes a
  **Brier score** (overall, and against the uncalibrated prior for comparison),
  a **reliability curve** (predicted vs observed hit rate per decile), and
  **per-agent** stated-vs-realized rates — the sentence that justifies or
  corrects a weight, e.g. "news at 0.80 is right 55% of the time."
- **Fit.** Once `CALIBRATION_MIN_SAMPLES` (default 50) outcomes resolve, a
  scheduled re-fit (`CALIBRATION_REFIT_HOURS`, default 24h) fits a **Platt
  scaling** (1-D logistic on `prior_confidence`) and stores it as a versioned,
  single-active `calibration_fits` row (method, params, N, Brier, through-date).
  The active fit is loaded process-wide and applied inside `derive_confidence`;
  the on-report rationale then reads *"Calibrated on N resolved reports through
  YYYY-MM."*
- **Cold start & guardrails.** Below the minimum — or if a fit's slope is
  non-positive (a perverse tiny-N fit) — the pipeline falls back to the
  hand-tuned prior, unchanged from pre-calibration behavior. The fit always
  trains on the *uncalibrated* prior, never on its own output (no feedback
  loop), and the final number is always clamped to `[0.05, 0.95]` — never
  certainty. A calibration failure never breaks a run.
- **Surfaced** at `GET /calibration` (aggregate, non-user methodology data) and
  in the report UI (`CalibrationCard`): reliability curve, Brier, per-agent
  rates, and the active fit's provenance.

**Limits (read these before trusting a number)**

- **Small N.** Early numbers are computed on tens of outcomes and coarse
  deciles — indicative, not statistically strong.
- **Self-selected sample.** Only tickers you watch or hold get scored, so the
  set carries selection/survivorship bias; it is not a random universe.
- **Choice-sensitive.** Results depend on the benchmark, band, and horizon; a
  different benchmark can flip a `neutral` verdict.
- **Backward-looking.** This is a *backtested description of past agreement*,
  **not** a prediction of future accuracy — and still not licensed investment
  advice.

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
                    SSE /research/{run}/events, /research/{run}/answer,
                    /health, /calibration (Phase 4 metrics)
    runs.py         run lifecycle: worker threads, interrupt/resume, SSE
    db.py           SQLAlchemy engine/session (SQLite by default)
    db_models.py    User / Holding / Preferences + WatchlistItem / StoredReport /
                    AlertRule / Notification / ReportOutcome / CalibrationFit tables
    calibration.py  Phase 4 confidence calibration: outcome backfill, Brier /
                    reliability / per-agent metrics, versioned Platt fit
    auth.py         bcrypt hashing, JWT create/verify, auth dependencies
    scheduler.py    APScheduler jobs (in-process): daily summary (cron) +
                    calibration backfill/refit (interval)
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
                    test_phase4 (watchlist, summaries, alerts, derived confidence),
                    test_phase4_calibration (Brier/reliability/Platt fit, backfill/refit)
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
created on first boot. SQLite runs in WAL mode with a busy-timeout so the
request threads, the run pool, and the scheduler job can write concurrently
without `database is locked`. That is enough for a single node; **beyond one
node, set `DATABASE_URL` to Postgres** (`postgresql+psycopg://…`) — the swap is
already wired. Set a real `JWT_SECRET` for anything beyond local development.

### Deploying (Phase 2 — security)

Before putting this on a public URL:

- **`ENV=prod` + a real `JWT_SECRET`.** Outside `dev` the app **refuses to
  boot** with the shipped default secret or anything under 32 bytes (so a
  reader of this repo can't forge tokens). Generate one:
  `python -c "import secrets; print(secrets.token_urlsafe(48))"`.
- **`SEC_USER_AGENT`** must be a real `AppName/version (you@example.com)` —
  the EDGAR tool refuses to fetch with the placeholder (SEC fair-access).
- **Rate limits & spend budget** are on by default: per-IP limits on
  `/research`, `/auth/*`, `/summaries/run`, `/recommendations/run`,
  `/digest/send-now`, plus a process-wide `DAILY_RUN_BUDGET` cap on research
  runs and a per-email login lockout. Tune via `.env` (see `.env.example`).
  Behind a reverse proxy, forward a trustworthy client IP or you rate-limit
  the proxy itself.
- **CORS:** set `CORS_ORIGINS` to your real frontend origin — never `*` with
  credentials. Terminate TLS and add security headers (HSTS,
  `X-Content-Type-Options`) at the proxy, not in app code.

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
- Each report is appended to `backend/recommendations_log.jsonl` and snapshotted
  as a `report_outcomes` row so recommendations are checked against realized
  outcomes (see [Confidence calibration](#confidence-calibration--closing-the-loop)).

## Tests

```bash
cd backend
# The whole suite in one go (pytest also discovers the module-style tests):
SCHEDULER_ENABLED=false python -m pytest tests/

# …or individually:
python -m tests.test_smoke      # Phase 1 contract + pipeline
python -m tests.test_phase2     # planner routing, interrupts, failure isolation
python -m tests.test_e2e_api    # full HTTP run: SSE + question/answer flow
python -m pytest tests/test_phase3.py  # auth, CRUD, portfolio agent, personalization
python -m pytest tests/test_phase4.py  # watchlist, summaries job, alerts, confidence
python -m pytest tests/test_phase4_calibration.py  # Brier/reliability/Platt fit, backfill, refit
```

`pytest` is in `requirements.txt`. No API keys needed — all tools are faked.
`test_e2e_api` binds port 8899, so keep it free.

## Roadmap

Phase 1 single pipeline ✅ → Phase 2 specialized agents + LangGraph planner ✅
→ Phase 3 portfolios/personalization ✅ → **Phase 4
watchlists/alerts/confidence UI ✅ (this)** → Phase 5 adaptive memory. See
`brainstorm/` for full phase specs.
