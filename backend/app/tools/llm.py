"""Report generation via the Anthropic API (Claude).

Structured output is guaranteed by forcing a single tool call whose input
schema *is* the report contract, so the model must return well-formed
claims/summary rather than free-text we'd have to parse.

Swap target: OpenAI (JSON mode), local models. Any class implementing
`LLMProvider` can replace this.
"""
from __future__ import annotations

import json

from anthropic import Anthropic

from app.config import settings
from app.models import AgentReport, Claim, MarketData, NewsItem, Recommendation
from app.tools.base import ToolError

_SYSTEM = (
    "You are a careful equity research analyst. You ground every claim in the "
    "evidence provided (market data and news). You never invent figures, prices, "
    "or sources. If the evidence is thin, you say so and lower your confidence. "
    "You produce research and education, not personalized investment advice."
)

# The tool schema IS the structured-output contract.
_REPORT_TOOL = {
    "name": "emit_research_report",
    "description": "Emit the structured research report. Call exactly once.",
    "input_schema": {
        "type": "object",
        "properties": {
            "claims": {
                "type": "array",
                "description": "3-7 sourced, confidence-scored claims.",
                "items": {
                    "type": "object",
                    "properties": {
                        "claim": {"type": "string"},
                        "evidence": {
                            "type": "string",
                            "description": "The concrete data point behind the claim.",
                        },
                        "source": {
                            "type": "string",
                            "description": "A URL or source name from the supplied evidence only.",
                        },
                        "confidence": {
                            "type": "number",
                            "minimum": 0.0,
                            "maximum": 1.0,
                        },
                    },
                    "required": ["claim", "evidence", "source", "confidence"],
                },
            },
            "summary": {
                "type": "string",
                "description": "2-4 sentence neutral synthesis of the claims.",
            },
        },
        "required": ["claims", "summary"],
    },
}


class AnthropicLLM:
    name = "anthropic"

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        key = api_key if api_key is not None else settings.anthropic_api_key
        if not key:
            raise ToolError("ANTHROPIC_API_KEY is not set; cannot generate report.")
        self._client = Anthropic(api_key=key)
        self._model = model or settings.anthropic_model

    def generate_claims(
        self, ticker: str, market: MarketData, news: list[NewsItem]
    ) -> tuple[list[Claim], str]:
        evidence = self._build_evidence(ticker, market, news)

        try:
            resp = self._client.messages.create(
                model=self._model,
                max_tokens=2000,
                system=_SYSTEM,
                tools=[_REPORT_TOOL],
                tool_choice={"type": "tool", "name": "emit_research_report"},
                messages=[{"role": "user", "content": evidence}],
            )
        except Exception as exc:  # noqa: BLE001 - normalize SDK/network errors
            raise ToolError(f"LLM request failed: {exc}") from exc

        payload = None
        for block in resp.content:
            if block.type == "tool_use" and block.name == "emit_research_report":
                payload = block.input
                break
        if payload is None:
            raise ToolError("LLM did not return a structured report.")

        claims = [Claim(**c) for c in payload.get("claims", [])]
        summary = payload.get("summary", "")
        return claims, summary

    @staticmethod
    def _build_evidence(
        ticker: str, market: MarketData, news: list[NewsItem]
    ) -> str:
        md = market.model_dump()
        news_lines = (
            "\n".join(
                f"- {n.title} ({n.source or 'unknown'}, {n.published_at or 'n/a'})"
                f" — {n.url}\n  {n.summary or ''}".rstrip()
                for n in news
            )
            or "(no news available)"
        )
        return (
            f"Produce a research report for {ticker}.\n\n"
            f"MARKET DATA (source: {market.source}):\n"
            f"{json.dumps(md, indent=2, default=str)}\n\n"
            f"RECENT NEWS:\n{news_lines}\n\n"
            "Rules:\n"
            "- Base every claim only on the data above.\n"
            "- Put the exact number in 'evidence' and a real URL/source name in 'source'.\n"
            "- If a data point is missing, do not guess — omit it or flag low confidence.\n"
            "- Return 3-7 claims plus a short neutral summary."
        )


# --- Phase 2: agent-specific structured LLM calls -----------------------------

_NEWS_CLAIMS_TOOL = {
    "name": "emit_news_claims",
    "description": "Emit claims about catalysts/risks found in the news. Call once.",
    "input_schema": {
        "type": "object",
        "properties": {
            "claims": _REPORT_TOOL["input_schema"]["properties"]["claims"],
        },
        "required": ["claims"],
    },
}

_RECOMMEND_TOOL = {
    "name": "emit_recommendation",
    "description": "Emit the final synthesis of the agents' claims. Call once.",
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {
                "type": "string",
                "description": "3-6 sentence synthesis citing the strongest claims.",
            },
            "stance": {"type": "string", "enum": ["bullish", "neutral", "bearish"]},
            "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        },
        "required": ["summary", "stance", "confidence"],
    },
}


class AnthropicAgentLLM:
    """Structured LLM calls for the News and Recommendation agents.

    Lenient constructor: the missing-key error is raised at call time so the
    orchestrator can turn it into a per-agent failure flag instead of a crash.
    """

    name = "anthropic-agents"

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        self._key = api_key if api_key is not None else settings.anthropic_api_key
        self._model = model or settings.anthropic_model
        self._client = Anthropic(api_key=self._key) if self._key else None

    def claims_from_news(self, ticker: str, news: list[NewsItem]) -> list[Claim]:
        if not news:
            return []
        news_lines = "\n".join(
            f"- {n.title} ({n.source or 'unknown'}, {n.published_at or 'n/a'})"
            f" — {n.url}\n  {n.summary or ''}".rstrip()
            for n in news
        )
        prompt = (
            f"From the news below, extract 2-5 claims about catalysts or risks for "
            f"{ticker}.\n\nRECENT NEWS:\n{news_lines}\n\n"
            "Rules:\n"
            "- Base every claim only on the articles above; 'source' must be one of "
            "their URLs.\n"
            "- Headlines are unverified — cap confidence at 0.7 unless multiple "
            "outlets agree.\n"
            "- Skip articles that are not actually about the company."
        )
        payload = self._call(prompt, _NEWS_CLAIMS_TOOL)
        return [Claim(**c) for c in payload.get("claims", [])]

    def recommend(
        self,
        ticker: str,
        agent_reports: list[AgentReport],
        lens: str | None,
        flags: list[str],
    ) -> Recommendation:
        # Input is ONLY the structured claims — never free text to re-parse.
        claims_json = json.dumps(
            [r.model_dump() for r in agent_reports], indent=2, default=str
        )
        lens_line = (
            f"Evaluate through a {lens} investing lens."
            if lens
            else "Use a balanced lens."
        )
        prompt = (
            f"Synthesize a final view on {ticker} from these structured, "
            f"per-agent claims:\n\n{claims_json}\n\n"
            f"DATA-QUALITY FLAGS: {flags or 'none'}\n\n"
            f"{lens_line}\n"
            "Rules:\n"
            "- Reason only from the claims above; do not introduce outside facts.\n"
            "- Weigh claims by their confidence scores; note conflicts explicitly.\n"
            "- If agents failed or data is flagged missing, lower your confidence "
            "and say what is missing."
        )
        payload = self._call(prompt, _RECOMMEND_TOOL)
        return Recommendation(
            summary=payload.get("summary", ""),
            stance=payload.get("stance", "neutral"),
            confidence=float(payload.get("confidence", 0.5)),
        )

    def _call(self, prompt: str, tool: dict) -> dict:
        if self._client is None:
            raise ToolError("ANTHROPIC_API_KEY is not set; LLM agent unavailable.")
        try:
            resp = self._client.messages.create(
                model=self._model,
                max_tokens=1500,
                system=_SYSTEM,
                tools=[tool],
                tool_choice={"type": "tool", "name": tool["name"]},
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as exc:  # noqa: BLE001
            raise ToolError(f"LLM request failed: {exc}") from exc
        for block in resp.content:
            if block.type == "tool_use" and block.name == tool["name"]:
                return block.input
        raise ToolError("LLM did not return structured output.")
