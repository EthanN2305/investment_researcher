"""Specialist agents.

Each agent gathers its own evidence and returns an `AgentReport` — the same
structured Claim contract from Phase 1. Design note: the News and
Recommendation agents need an LLM (interpretation); Financials, Valuation,
Technicals and Market Risk derive claims deterministically from numeric
data, which keeps them fast, cheap, and unit-testable. The Peer Comparison
agent is a hybrid: the LLM names the peer group (judgment), but every figure
is fetched from market data and benchmarked deterministically.
"""
from .news import NewsAgent
from .financials import FinancialStatementAgent
from .valuation import ValuationAgent
from .technicals import TechnicalAnalysisAgent
from .recommend import RecommendationAgent
from .portfolio import PortfolioManagerAgent
from .risk import MarketRiskAgent
from .comps import PeerComparisonAgent

__all__ = [
    "NewsAgent",
    "FinancialStatementAgent",
    "ValuationAgent",
    "TechnicalAnalysisAgent",
    "RecommendationAgent",
    "PortfolioManagerAgent",
    "MarketRiskAgent",
    "PeerComparisonAgent",
]
