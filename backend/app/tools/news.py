"""Recent news via NewsAPI.org (free developer tier).

Swap target: Benzinga, Finnhub news, RSS feeds. Any class implementing
`NewsProvider` can replace this.

Free-tier notes: dev key is rate-limited and restricted to non-production use,
and articles are limited to the last ~30 days. We query the company name when
available for better recall, falling back to the ticker.
"""
from __future__ import annotations

import httpx

from app.config import settings
from app.models import NewsItem
from app.tools.base import ToolError

_ENDPOINT = "https://newsapi.org/v2/everything"


class NewsAPINews:
    name = "newsapi"

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key if api_key is not None else settings.newsapi_key

    def get_news(self, ticker: str, limit: int = 8) -> list[NewsItem]:
        if not self._api_key:
            raise ToolError("NEWSAPI_KEY is not set; cannot fetch news.")

        query = ticker.strip().upper()
        params = {
            "q": query,
            "language": "en",
            "sortBy": "publishedAt",
            "pageSize": max(1, min(limit, 20)),
            "apiKey": self._api_key,
        }

        try:
            resp = httpx.get(_ENDPOINT, params=params, timeout=15.0)
        except httpx.HTTPError as exc:
            raise ToolError(f"News request failed: {exc}") from exc

        if resp.status_code == 429:
            raise ToolError("NewsAPI rate limit reached (free tier).")
        if resp.status_code == 401:
            raise ToolError("NewsAPI rejected the key (401).")
        if resp.status_code != 200:
            raise ToolError(f"NewsAPI error {resp.status_code}: {resp.text[:200]}")

        data = resp.json()
        articles = data.get("articles", [])
        items: list[NewsItem] = []
        for a in articles[:limit]:
            items.append(
                NewsItem(
                    title=a.get("title") or "(untitled)",
                    url=a.get("url") or "",
                    source=(a.get("source") or {}).get("name"),
                    published_at=a.get("publishedAt"),
                    summary=a.get("description"),
                )
            )
        return items
