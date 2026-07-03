# Phase 3 — Portfolios, Preferences, and Personalized Recommendations

## Goal
Introduce user accounts. Users can create portfolios, store investment
preferences, and receive recommendations personalized against their actual
holdings and stated risk tolerance — via a new Portfolio Manager Agent.

## Scope
- First phase requiring persistence and auth.
- Existing Phase 2 agent pipeline stays intact; this phase adds a personalization
  layer on top of it.

## Requirements
- **Auth & accounts:** basic user sign-up/login (email/password or OAuth —
  whichever is faster to stand up). Session handling in FastAPI.
- **Database:** store users, portfolios (ticker, quantity, cost basis), and
  preferences (risk tolerance, sector interests, growth vs value lean, time
  horizon). A simple Postgres schema is enough — no need for anything exotic.
- **Portfolio Manager Agent:**
  - Reads the user's stored portfolio and preferences
  - Adds its own structured claims (same format as other agents) reflecting how
    a given ticker fits — or doesn't — with the user's existing holdings and
    stated preferences (e.g. concentration risk, sector overlap, mismatch with
    stated risk tolerance)
  - Feeds into the Recommendation Agent alongside the other Phase 2 agents, so
    the final report is personalized, not generic
- **API endpoints:** CRUD for portfolios and preferences; existing research
  endpoint updated to optionally personalize when a logged-in user requests it
- **Frontend:**
  - Sign-up/login flow
  - Portfolio entry/edit UI (add/remove holdings)
  - Preferences form (risk tolerance, sectors, horizon, etc.)
  - Research report view updated to show the Portfolio Manager Agent's
    "how this fits your portfolio" section distinctly from the general analysis

## Explicitly out of scope for this phase
- Watchlists, alerts, daily summaries (Phase 4)
- Confidence-score UI polish (Phase 4)
- Adaptive/learned memory beyond explicitly stored preferences (Phase 5) — this
  phase uses only what the user directly tells it, not inferred behavior

## Starter Prompt

> Extend the Phase 2 multi-agent investment research tool to support user
> accounts, stored portfolios, and personalized recommendations.
>
> Requirements:
> - Add basic authentication (sign-up/login) and a database (Postgres is fine)
>   storing users, their portfolio holdings (ticker, quantity, cost basis), and
>   their stated preferences (risk tolerance, sector interests, growth/value
>   lean, time horizon).
> - Build a Portfolio Manager Agent that reads a logged-in user's stored
>   portfolio and preferences, and produces structured claims (same
>   claim/evidence/source/confidence format as the other agents) about how the
>   researched ticker fits their existing holdings — e.g. concentration risk,
>   sector overlap, or mismatch with stated risk tolerance.
> - Feed the Portfolio Manager Agent's output into the existing Recommendation
>   Agent alongside the Phase 2 agents so personalized context shapes the final
>   report when the user is logged in; the tool should still work for
>   non-logged-in, generic requests.
> - Add CRUD endpoints for portfolios and preferences.
> - Add frontend flows for sign-up/login, portfolio entry/editing, and a
>   preferences form, and update the report view to show a distinct
>   "how this fits your portfolio" section.
