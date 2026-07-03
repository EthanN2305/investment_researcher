"""Swappable data/LLM tools.

Each tool is defined as a Protocol interface, with one concrete
implementation wired up as the default. Providers can be swapped in
`app.graph.build` without touching agent or report logic.
"""
from .base import (
    AgentLLMProvider,
    FinancialsProvider,
    LLMProvider,
    MarketDataProvider,
    NewsProvider,
    PriceHistoryProvider,
)
from .market_data import YFinanceMarketData
from .news import NewsAPINews
from .llm import AnthropicLLM, AnthropicAgentLLM
from .edgar import SecEdgarFinancials
from .prices import YFinancePriceHistory

__all__ = [
    "MarketDataProvider",
    "NewsProvider",
    "LLMProvider",
    "AgentLLMProvider",
    "FinancialsProvider",
    "PriceHistoryProvider",
    "YFinanceMarketData",
    "NewsAPINews",
    "AnthropicLLM",
    "AnthropicAgentLLM",
    "SecEdgarFinancials",
    "YFinancePriceHistory",
]
