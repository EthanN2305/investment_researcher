"""Recommendation Agent — final synthesis.

Consumes ONLY the merged structured claims from the other agents (their
AgentReports), never free text. If the LLM is unavailable the run still
completes, with a flag and a data-only fallback summary.
"""
from __future__ import annotations

from app.models import AgentReport, Recommendation
from app.tools.base import AgentLLMProvider, ToolError

AGENT_ID = "recommendation"


class RecommendationAgent:
    def __init__(self, llm: AgentLLMProvider) -> None:
        self._llm = llm

    def run(
        self,
        ticker: str,
        agent_reports: list[AgentReport],
        lens: str | None,
        flags: list[str],
    ) -> tuple[Recommendation, list[str]]:
        usable = [r for r in agent_reports if r.claims]
        if not usable:
            return (
                Recommendation(
                    summary=f"No agent produced claims for {ticker}; "
                            "no synthesis is possible.",
                    stance="neutral",
                    confidence=0.1,
                ),
                ["no_claims_to_synthesize"],
            )
        try:
            return self._llm.recommend(ticker, usable, lens, flags), []
        except ToolError:
            n = sum(len(r.claims) for r in usable)
            return (
                Recommendation(
                    summary=f"Synthesis unavailable (LLM error). {n} structured "
                            f"claims from {len(usable)} agents are shown below.",
                    stance="neutral",
                    confidence=0.2,
                ),
                ["recommendation_llm_failed"],
            )
