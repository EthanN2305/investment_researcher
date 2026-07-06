"""Planner/Orchestrator node.

Decides which agents to run (quick check vs deep dive) and pauses the run
with `interrupt()` when information is missing or ambiguous — the answer
arrives via `Command(resume=...)` and the node re-executes deterministically
(LangGraph replays earlier interrupt() calls from the checkpoint).
"""
from __future__ import annotations

from langgraph.types import interrupt

from app.graph import events
from app.graph.state import PLANS, ResearchState

# Companies with two commonly-traded share classes — a classic ambiguity the
# planner should resolve by asking rather than guessing.
SHARE_CLASSES: dict[str, list[str]] = {
    "GOOG": ["GOOGL (Class A, voting)", "GOOG (Class C, non-voting)"],
    "GOOGL": ["GOOGL (Class A, voting)", "GOOG (Class C, non-voting)"],
    "BRK": ["BRK-A (Class A)", "BRK-B (Class B)"],
    "BRK.A": ["BRK-A (Class A)", "BRK-B (Class B)"],
    "BRK.B": ["BRK-A (Class A)", "BRK-B (Class B)"],
    "FOX": ["FOXA (Class A)", "FOX (Class B)"],
    "NWS": ["NWSA (Class A)", "NWS (Class B)"],
    "UA": ["UAA (Class A)", "UA (Class C)"],
}

_DEPTHS = ("quick", "deep")
_LENSES = ("growth", "value", "balanced")


def _extract_ticker(answer: str) -> str:
    """'GOOGL (Class A, voting)' -> 'GOOGL'; free-text answers pass through."""
    return answer.strip().upper().split()[0].split("(")[0].strip(".,")


def planner_node(state: ResearchState) -> dict:
    run_id = state["run_id"]
    ticker = state["ticker"].strip().upper()
    events.emit(run_id, {"type": "status", "agent": "planner", "state": "started",
                         "message": f"Planning research for {ticker}…"})

    # 1) Ambiguous share class → ask, don't guess.
    if ticker in SHARE_CLASSES:
        options = SHARE_CLASSES[ticker]
        answer = interrupt({
            "question": f"{ticker} has more than one share class — "
                        "which one did you mean?",
            "options": options,
        })
        ticker = _extract_ticker(str(answer)) or ticker

    # 2) Unknown depth → ask quick check vs deep dive.
    depth = (state.get("depth") or "").lower()
    if depth not in _DEPTHS:
        answer = interrupt({
            "question": "Do you want a quick check (technicals + valuation) or a "
                        "deep dive (news, SEC financials, technicals, market "
                        "risk, peer comparison, valuation)?",
            "options": ["quick", "deep"],
        })
        depth = "deep" if "deep" in str(answer).lower() else "quick"

    # 3) Deep dives need a lens for the recommendation synthesis.
    lens = (state.get("lens") or "").lower() or None
    if depth == "deep" and lens not in _LENSES:
        answer = interrupt({
            "question": "Should the recommendation use a growth or value lens?",
            "options": ["growth", "value", "balanced"],
        })
        a = str(answer).lower()
        lens = next((l for l in _LENSES if l in a), "balanced")

    plan = list(PLANS[depth])
    # Phase 3: a logged-in, personalized run adds the Portfolio Manager Agent.
    if state.get("portfolio_context"):
        plan.append("portfolio")
    events.emit(run_id, {"type": "plan", "ticker": ticker, "depth": depth,
                         "lens": lens, "agents": plan + ["recommendation"]})
    events.emit(run_id, {"type": "status", "agent": "planner", "state": "done",
                         "message": f"Running {len(plan)} agents ({depth} mode)."})
    return {"ticker": ticker, "depth": depth, "lens": lens, "plan": plan}
