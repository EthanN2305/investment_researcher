# Backend — Phase 2

FastAPI service running a LangGraph multi-agent graph. Runs are in-memory
(no accounts/persistence until Phase 3).

## Run

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # fill ANTHROPIC_API_KEY, NEWSAPI_KEY
uvicorn app.main:app --reload --port 8000
```

## Endpoints

- `GET  /health` — status + which keys are configured
- `POST /research` — body `{"ticker": "AAPL", "depth": "deep"|"quick"|null, "lens": "growth"|"value"|"balanced"|null}` → `{run_id}`.
  Omit `depth`/`lens` and the planner will ask instead of guessing.
- `GET  /research/{run_id}/events` — **SSE** stream of run events (below)
- `POST /research/{run_id}/answer` — body `{"answer": "..."}`; resumes an
  interrupted run (409 if the run isn't waiting)
- `GET  /research/{run_id}` — poll fallback: status + report once done
- `GET  /docs` — interactive OpenAPI UI

## SSE events

Each frame is `data: {json}`:

| type       | payload                                                  |
|------------|----------------------------------------------------------|
| `plan`     | `ticker, depth, lens, agents[]` — what the planner chose |
| `status`   | `agent, state: started/done/failed, message`             |
| `question` | `question, options[]` — run paused; POST an answer       |
| `report`   | `report` — the `FinalReport`                             |
| `done` / `error` | terminal                                           |

The stream stays open across questions — answer via POST and progress
continues on the same connection.

## Graph topology

```
planner ─Send─▶ news ────────┐
        ─Send─▶ financials ──┼─▶ gather ─▶ valuation ─▶ recommendation ─▶ END
        ─Send─▶ technicals ──┘             (skipped on plans without it)
```

- Planner fans out only to the planned agents (quick = technicals+valuation,
  deep = all four). Stage-1 agents run in parallel.
- Valuation runs second-stage so it can use the financials agent's EDGAR
  figures (P/S, earnings multiple).
- Clarifying questions use LangGraph `interrupt()` + an `InMemorySaver`
  checkpoint; `Command(resume=answer)` continues the run.
- Any agent exception → `AgentReport(status="failed")` + `<agent>_unavailable`
  flag; the run never crashes.
- The Recommendation Agent receives only `AgentReport` objects (structured
  claims) — never raw text.

## Data sources

- Market data + price history: yfinance (rate-limit-hardened, cached)
- Fundamentals: SEC EDGAR `companyfacts` XBRL API (annual 10-K facts; keyless,
  requires a contact User-Agent — `SEC_USER_AGENT` in `.env`)
- News: NewsAPI.org (free tier)
- LLM (news claims + recommendation synthesis): Anthropic, structured output
  via forced tool call

All behind Protocols in `app/tools/base.py` — swap by passing a different
implementation to `build_graph()` in `app/main.py`.

## Error handling

- Invalid ticker → `422`; unknown run → `404`; answer when not waiting → `409`.
- Agent/tool failures → report flags (run completes).
- Missing API keys → affected agents fail soft with flags; `/health` shows
  which keys are set.

## Tests

```bash
python -m tests.test_smoke      # Phase 1 contract (still green)
python -m tests.test_phase2     # graph: routing, interrupts, failure isolation
python -m tests.test_e2e_api    # real server: SSE + question/answer round trip
```
