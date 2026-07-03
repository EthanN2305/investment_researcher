# Phase 2 — Specialized Agents + Planner

## Goal
Split Phase 1's single pipeline into distinct specialized agents, coordinated by a
Planner/Orchestrator agent using LangGraph. The planner can also ask the user for
missing information mid-run instead of guessing.

## Scope
- Still no user accounts/persistence — focus is entirely on multi-agent
  orchestration.
- Introduce LangGraph as the state machine coordinating agents.

## Requirements
- Convert Phase 1's single pipeline into separate agents, each returning the same
  structured claims format established in Phase 1:
  - **News Agent** — recent news, catalysts
  - **Financial Statement Agent** — revenue, margins, debt (SEC EDGAR data)
  - **Valuation Agent** — P/E, P/S and similar, derived from market + financial data
  - **Technical Analysis Agent** — moving averages, RSI, trend signals from price
    history
- Build a **Planner/Orchestrator agent** that:
  - Decides which agents to run and in what order (not all requests need all
    agents — e.g. a "quick check" vs a "deep dive")
  - Merges each agent's structured output into a shared LangGraph state object
  - Detects missing or insufficient data and can pause to ask the user a
    clarifying question (e.g. "This company has two share classes — which one did
    you mean?" or "Do you want a growth or value lens?") before continuing
  - Handles a single agent failing without crashing the whole run (e.g. news API
    down → continue with a flag noting news data is missing)
- A **Recommendation Agent** that consumes the merged structured claims from all
  other agents and produces the final report — it should never re-parse free text,
  only structured claims.
- Frontend updates:
  - Show live progress as each agent runs (e.g. via SSE/WebSocket: "Fetching
    financials...", "Reading news...", "Analyzing technicals...")
  - Support the planner's clarifying-question flow: if the planner asks a
    question, show it to the user and resume the run with their answer
  - Final report view groups claims by which agent produced them, plus the
    Recommendation Agent's synthesis

## Explicitly out of scope for this phase
- User accounts, portfolios, watchlists
- Competitor comparison agent (can be added here or deferred — optional stretch)
- Confidence-score visualization polish (basic display is enough; Phase 4 refines
  this)
- Memory or personalization

## Starter Prompt

> Extend the Phase 1 investment research tool into a multi-agent system
> orchestrated with LangGraph.
>
> Requirements:
> - Split the existing single research pipeline into separate agents: News
>   Agent, Financial Statement Agent, Valuation Agent, and Technical Analysis
>   Agent. Each returns the same structured claims format used in Phase 1
>   (claim, evidence, source, confidence).
> - Build a Planner/Orchestrator agent using LangGraph that decides which agents
>   to run, merges their structured output into shared graph state, and can pause
>   a run to ask the user a clarifying question when information is missing or
>   ambiguous, then resume once answered.
> - Build a Recommendation Agent that consumes only the merged structured claims
>   from other agents (never free text) and produces the final report.
> - Handle a single agent's failure gracefully — the run should continue with a
>   flag noting the missing data, not crash.
> - Update the React frontend to show live per-agent progress (via SSE or
>   WebSocket), support the planner's clarifying-question flow, and render the
>   final report grouped by contributing agent.
