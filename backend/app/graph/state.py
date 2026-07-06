"""Shared LangGraph state.

Every agent writes into `agent_reports` / `flags` via reducers, so parallel
fan-out branches merge cleanly instead of clobbering each other.
"""
from __future__ import annotations

import operator
from typing import Annotated, TypedDict

from app.models import AgentReport, FinalReport


def merge_reports(
    left: dict[str, AgentReport] | None, right: dict[str, AgentReport] | None
) -> dict[str, AgentReport]:
    return {**(left or {}), **(right or {})}


class ResearchState(TypedDict, total=False):
    run_id: str
    ticker: str
    depth: str  # "quick" | "deep" (planner resolves if absent)
    lens: str | None  # "growth" | "value" | "balanced"
    plan: list[str]  # agent ids the planner chose to run
    # Phase 3: snapshot of the logged-in user's holdings + preferences
    # (a PortfolioContext dump). None/absent → generic, non-personalized run.
    portfolio_context: dict | None
    agent_reports: Annotated[dict[str, AgentReport], merge_reports]
    flags: Annotated[list[str], operator.add]
    final_report: FinalReport


# Stage-1 agents can run in parallel; valuation runs after (it consumes the
# financials agent's output from state); recommendation runs last.
# Risk (beta vs SPY) and comps (peer benchmarking) are independent of the
# other agents, so they join the parallel stage-1 fan-out.
STAGE1_AGENTS = ("news", "financials", "technicals", "risk", "comps")

PLANS: dict[str, list[str]] = {
    # Quick check: price-action + market-based valuation only (fast, no LLM).
    "quick": ["technicals", "valuation"],
    # Deep dive: everything.
    "deep": ["news", "financials", "technicals", "risk", "comps", "valuation"],
}
