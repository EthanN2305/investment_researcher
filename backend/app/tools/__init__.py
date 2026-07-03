"""Swappable data/LLM tools.

Each tool is defined as a Protocol interface, with one concrete
implementation wired up as the default. Providers can be swapped in
`app.pipeline` without touching report logic.
"""
from .base import LLMProvider, MarketDataProvider, NewsProvider
from .market_data import YFinanceMarketData
from .news import NewsAPINews
from .llm import AnthropicLLM

__all__ = [
    "MarketDataProvider",
    "NewsProvider",
    "LLMProvider",
    "YFinanceMarketData",
    "NewsAPINews",
    "AnthropicLLM",
]
