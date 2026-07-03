# Phase 4 — Watchlists, Alerts, Daily Summaries, Confidence Scores

## Goal
Add ongoing engagement features on top of the on-demand research tool: watchlists,
scheduled daily AI summaries, alerts, and a fully surfaced, confidence-scored
reasoning chain in the UI.

## Scope
- Builds directly on Phase 3's accounts/portfolios.
- Introduces scheduled/background jobs for the first time.

## Requirements
- **Watchlists:** users can add/remove tickers to a watchlist independent of
  their portfolio holdings (things they're tracking but don't own yet).
- **Scheduled daily summaries:**
  - A background job (e.g. Celery, APScheduler, or a cron-triggered FastAPI task)
    runs the Phase 2 agent pipeline once daily per watchlist/portfolio ticker
  - Results are stored, not just streamed live, so they can be viewed later
    without re-running agents
  - Summary should be short (a few sentences) with a link/expand to the full
    structured report
- **Alerts:**
  - Define a small set of alert conditions (e.g. price moves >X%, a new
    high-confidence claim appears, a negative-news claim appears)
  - Notify via in-app notification at minimum; email is a reasonable stretch
  - Let users configure which tickers/conditions they want alerts for
- **Explainable reasoning UI:**
  - Every claim already carries a confidence score (from Phase 1) — this phase is
    about actually surfacing it well: visual confidence indicators, ability to
    expand a claim to see its evidence and source, and grouping by contributing
    agent
  - Show the Recommendation Agent's overall confidence for the final
    recommendation, derived from (not just averaged from, ideally reasoned over)
    the underlying agents' confidence levels
- **Frontend:**
  - Watchlist view (separate from portfolio view)
  - Daily summary feed/dashboard
  - Alert configuration screen and notification display
  - Reworked report view with expandable, confidence-annotated claims

## Explicitly out of scope for this phase
- Adaptive memory / learning from user behavior (Phase 5)
- New data-gathering agents (competitor agent etc. can be added here as a
  stretch, but isn't the focus)

## Starter Prompt

> Extend the Phase 3 investment research tool with watchlists, scheduled daily
> summaries, alerts, and a fully surfaced explainable-reasoning UI.
>
> Requirements:
> - Add watchlists: users can track tickers independently of portfolio holdings.
> - Add a background job (Celery, APScheduler, or scheduled task) that runs the
>   existing agent pipeline once daily for each watchlist/portfolio ticker and
>   stores the resulting structured report, so it can be viewed later without
>   re-running agents live.
> - Add an alerting system: a small set of configurable conditions (e.g. price
>   move beyond a threshold, a new high-confidence claim, a negative-news claim)
>   that trigger in-app notifications (email as a stretch), configurable per
>   ticker by the user.
> - Rework the report UI to fully surface the confidence scores already present
>   in each agent's structured claims: expandable claims showing evidence and
>   source, grouped by contributing agent, plus an overall confidence for the
>   Recommendation Agent's final call that's reasoned over the underlying
>   agents' confidence levels rather than a flat average.
> - Add a daily summary dashboard/feed and a watchlist view to the frontend.
