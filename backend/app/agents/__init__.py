"""Phase 2 specialist agents.

Each agent gathers its own evidence and returns an `AgentReport` — the same
structured Claim contract from Phase 1. Design note: the News and
Recommendation agents need an LLM (interpretation); Financials, Valuation and
Technicals derive claims deterministically from numeric data, which keeps
them fast, cheap, and unit-testable.
"""
from .news import NewsAgent
from .financials import FinancialStatementAgent
from .valuation import ValuationAgent
from .technicals import TechnicalAnalysisAgent
from .recommend import RecommendationAgent
from .portfolio import PortfolioManagerAgent

__all__ = [
    "NewsAgent",
    "FinancialStatementAgent",
    "ValuationAgent",
    "TechnicalAnalysisAgent",
    "RecommendationAgent",
    "PortfolioManagerAgent",
]
