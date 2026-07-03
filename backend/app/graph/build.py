"""Graph assembly.

Topology:

    planner ──Send──▶ news ─────┐
            ──Send──▶ financials ─▶ gather ─▶ (valuation?) ─▶ recommend ─▶ END
            ──Send──▶ technicals ┘

- The planner fans out ONLY to the agents in its plan (dynamic Send edges).
- Stage-1 agents run in parallel in one superstep; `gather` joins them.
- Valuation runs after gather so it can consume the financials agent's EDGAR
  figures from shared state.
- Any single agent failure becomes a `<agent>_unavailable` flag; the run
  continues (a core Phase 2 requirement).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Callable

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from app.agents import (
    FinancialStatementAgent,
    NewsAgent,
    RecommendationAgent,
    TechnicalAnalysisAgent,
    ValuationAgent,
)
from app.graph import events
from app.graph.planner import planner_node
from app.graph.state import STAGE1_AGENTS, ResearchState
from app.models import AgentReport, FinalReport
from app.tools.base import (
    AgentLLMProvider,
    FinancialsProvider,
    MarketDataProvider,
    NewsProvider,
    PriceHistoryProvider,
)

logger = logging.getLogger("graph")

_AGENT_LABELS = {
    "news": "Reading news",
    "financials": "Fetching SEC financials",
    "technicals": "Analyzing technicals",
    "valuation": "Computing valuation",
    "recommendation": "Synthesizing recommendation",
}


def _guarded(name: str, fn: Callable[[ResearchState], AgentReport]):
    """Wrap an agent so a failure becomes a flagged AgentReport, not a crash."""

    def node(state: ResearchState) -> dict:
        run_id = state["run_id"]
        events.emit(run_id, {"type": "status", "agent": name, "state": "started",
                             "message": f"{_AGENT_LABELS.get(name, name)}…"})
        try:
            report = fn(state)
        except Exception as exc:  # noqa: BLE001 — isolate agent failures
            logger.warning("agent %s failed for %s: %s", name, state["ticker"], exc)
            report = AgentReport(
                agent=name, status="failed", flags=[f"{name}_unavailable"]
            )
            events.emit(run_id, {"type": "status", "agent": name, "state": "failed",
                                 "message": str(exc)[:200]})
        else:
            events.emit(run_id, {
                "type": "status", "agent": name, "state": "done",
                "message": f"{len(report.claims)} claims",
            })
        return {"agent_reports": {name: report}, "flags": list(report.flags)}

    return node


def build_graph(
    *,
    market: MarketDataProvider,
    news: NewsProvider,
    financials: FinancialsProvider,
    prices: PriceHistoryProvider,
    llm: AgentLLMProvider,
    checkpointer=None,
):
    news_agent = NewsAgent(news, llm)
    fin_agent = FinancialStatementAgent(financials)
    tech_agent = TechnicalAnalysisAgent(prices)
    val_agent = ValuationAgent(market)
    rec_agent = RecommendationAgent(llm)

    def route_stage1(state: ResearchState):
        stage1 = [a for a in state["plan"] if a in STAGE1_AGENTS]
        if not stage1:
            return ["gather"]
        return [Send(a, dict(state)) for a in stage1]

    def gather_node(state: ResearchState) -> dict:
        return {}  # join point for the parallel stage-1 branches

    def route_after_gather(state: ResearchState) -> str:
        return "valuation" if "valuation" in state["plan"] else "recommendation"

    def run_valuation(state: ResearchState) -> AgentReport:
        # If the financials agent succeeded, pull the same EDGAR figures for
        # ratio math (the client caches, so this second call is ~free).
        fin_report = (state.get("agent_reports") or {}).get("financials")
        fin = None
        if fin_report is not None and fin_report.status == "ok":
            try:
                fin = financials.get_financials(state["ticker"])
            except Exception:  # noqa: BLE001
                fin = None
        return val_agent.run(state["ticker"], financials=fin)

    def recommend_node(state: ResearchState) -> dict:
        run_id = state["run_id"]
        events.emit(run_id, {"type": "status", "agent": "recommendation",
                             "state": "started",
                             "message": "Synthesizing recommendation…"})
        ordered = [state["agent_reports"][a] for a in state["plan"]
                   if a in (state.get("agent_reports") or {})]
        flags = sorted(set(state.get("flags") or []))
        recommendation, rec_flags = rec_agent.run(
            state["ticker"], ordered, state.get("lens"), flags
        )
        flags = sorted(set(flags + rec_flags))
        report = FinalReport(
            ticker=state["ticker"],
            depth=state.get("depth", "deep"),
            lens=state.get("lens"),
            agent_reports=ordered,
            recommendation=recommendation,
            flags=flags,
            generated_at=datetime.now(timezone.utc).isoformat(),
        )
        events.emit(run_id, {"type": "status", "agent": "recommendation",
                             "state": "done", "message": recommendation.stance})
        return {"final_report": report, "flags": rec_flags}

    builder = StateGraph(ResearchState)
    builder.add_node("planner", planner_node)
    builder.add_node("news", _guarded("news", lambda s: news_agent.run(s["ticker"])))
    builder.add_node(
        "financials", _guarded("financials", lambda s: fin_agent.run(s["ticker"]))
    )
    builder.add_node(
        "technicals", _guarded("technicals", lambda s: tech_agent.run(s["ticker"]))
    )
    builder.add_node("gather", gather_node)
    builder.add_node("valuation", _guarded("valuation", run_valuation))
    builder.add_node("recommendation", recommend_node)

    builder.add_edge(START, "planner")
    builder.add_conditional_edges("planner", route_stage1, list(STAGE1_AGENTS) + ["gather"])
    for a in STAGE1_AGENTS:
        builder.add_edge(a, "gather")
    builder.add_conditional_edges(
        "gather", route_after_gather, ["valuation", "recommendation"]
    )
    builder.add_edge("valuation", "recommendation")
    builder.add_edge("recommendation", END)

    return builder.compile(checkpointer=checkpointer or InMemorySaver())
