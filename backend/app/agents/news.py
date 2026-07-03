"""News Agent — recent news and catalysts.

Fetches headlines (NewsAPI) and uses the LLM to turn them into structured
claims. Headlines are unverified, so confidence is capped in the prompt.
"""
from __future__ import annotations

from app.models import AgentReport
from app.tools.base import AgentLLMProvider, NewsProvider

AGENT_ID = "news"


class NewsAgent:
    def __init__(self, news: NewsProvider, llm: AgentLLMProvider) -> None:
        self._news = news
        self._llm = llm

    def run(self, ticker: str) -> AgentReport:
        items = self._news.get_news(ticker)
        if not items:
            return AgentReport(agent=AGENT_ID, flags=["no_recent_news"])
        claims = self._llm.claims_from_news(ticker, items)
        flags = ["no_claims_from_news"] if not claims else []
        return AgentReport(agent=AGENT_ID, claims=claims, flags=flags)
