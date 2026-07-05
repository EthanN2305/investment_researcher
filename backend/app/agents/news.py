"""News Agent — recent news and catalysts.

Fetches headlines (NewsAPI) and uses the LLM to turn them into structured
claims. Headlines are unverified, so confidence is capped in the prompt.

Recency discipline from Anthropic's financial-services `earnings-analysis`
skill (its "training data is outdated" rule): every run verifies article
dates before interpretation. If nothing in the feed is recent, the report is
flagged `stale_news` so the Recommendation Agent can discount news-derived
claims instead of treating old headlines as current catalysts.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models import AgentReport, NewsItem
from app.tools.base import AgentLLMProvider, NewsProvider

AGENT_ID = "news"
STALE_AFTER_DAYS = 14


def _parse_date(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _is_stale(items: list[NewsItem]) -> bool:
    """True when no article has a parseable date within STALE_AFTER_DAYS."""
    dates = [d for d in (_parse_date(n.published_at) for n in items) if d]
    if not dates:
        return False  # undated feed — can't judge, don't punish
    cutoff = datetime.now(timezone.utc) - timedelta(days=STALE_AFTER_DAYS)
    return max(dates) < cutoff


class NewsAgent:
    def __init__(self, news: NewsProvider, llm: AgentLLMProvider) -> None:
        self._news = news
        self._llm = llm

    def run(self, ticker: str) -> AgentReport:
        items = self._news.get_news(ticker)
        if not items:
            return AgentReport(agent=AGENT_ID, flags=["no_recent_news"])
        flags: list[str] = []
        if _is_stale(items):
            flags.append("stale_news")
        claims = self._llm.claims_from_news(ticker, items)
        if not claims:
            flags.append("no_claims_from_news")
        return AgentReport(agent=AGENT_ID, claims=claims, flags=flags)
