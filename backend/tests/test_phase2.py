"""Phase 2 tests — no API keys or network required (all tools are fakes).

Run: cd backend && python -m tests.test_phase2
Covers: planner routing (quick vs deep), interrupt/resume clarifying-question
flow, share-class ambiguity, per-agent failure isolation, valuation's use of
financials, and the Recommendation Agent's structured-claims-only contract.
"""
from __future__ import annotations

from langgraph.types import Command

from app.graph import build_graph
from app.models import (
    AgentReport,
    Claim,
    Financials,
    MarketData,
    NewsItem,
    PriceHistory,
    Recommendation,
)
from app.tools.base import ToolError


# --- Fakes --------------------------------------------------------------------
class FakeMarket:
    name = "fake-market"

    def get_market_data(self, ticker: str) -> MarketData:
        return MarketData(
            ticker=ticker, name="Fake Corp", price=100.0, currency="USD",
            market_cap=1_000_000_000, pe_ratio=20.0,
            fifty_two_week_high=120.0, fifty_two_week_low=80.0,
        )


class FakeNews:
    name = "fake-news"

    def get_news(self, ticker: str, limit: int = 8) -> list[NewsItem]:
        return [NewsItem(title=f"{ticker} wins big contract",
                         url="https://example.com/a")]


class FailingNews:
    name = "failing-news"

    def get_news(self, ticker: str, limit: int = 8):
        raise ToolError("simulated news outage")


class FakeEdgar:
    name = "fake-edgar"

    def get_financials(self, ticker: str) -> Financials:
        return Financials(
            ticker=ticker, company="Fake Corp", fiscal_year_end="2025-12-31",
            revenue=500_000_000, revenue_prior=400_000_000,
            net_income=50_000_000, total_debt=100_000_000,
            stockholders_equity=200_000_000, source="https://sec.example/facts",
        )


class FakePrices:
    name = "fake-prices"

    def get_history(self, ticker: str, period: str = "1y") -> PriceHistory:
        closes = [100 + (i % 7) - 3 + i * 0.1 for i in range(250)]  # gentle uptrend
        return PriceHistory(
            ticker=ticker,
            dates=[f"2025-{1 + i // 21:02d}-{1 + i % 21:02d}" for i in range(250)],
            closes=closes,
        )


class FakeAgentLLM:
    name = "fake-agent-llm"

    def claims_from_news(self, ticker, news):
        return [Claim(claim=f"{ticker} secured a major contract (catalyst).",
                      evidence=news[0].title, source=news[0].url, confidence=0.6)]

    def recommend(self, ticker, agent_reports, lens, flags):
        assert all(isinstance(r, AgentReport) for r in agent_reports), \
            "recommendation must receive structured AgentReports only"
        return Recommendation(
            summary=f"Synthesis of {sum(len(r.claims) for r in agent_reports)} "
                    f"claims under a {lens or 'balanced'} lens.",
            stance="bullish", confidence=0.7,
        )


class FailingAgentLLM(FakeAgentLLM):
    def recommend(self, ticker, agent_reports, lens, flags):
        raise ToolError("simulated LLM outage")


def make_graph(news=None, llm=None):
    return build_graph(
        market=FakeMarket(), news=news or FakeNews(), financials=FakeEdgar(),
        prices=FakePrices(), llm=llm or FakeAgentLLM(),
    )


def cfg(tid: str) -> dict:
    return {"configurable": {"thread_id": tid}}


# --- Tests ----------------------------------------------------------------------
def test_deep_run_all_agents():
    g = make_graph()
    out = g.invoke({"run_id": "t1", "ticker": "aapl", "depth": "deep",
                    "lens": "growth"}, cfg("t1"))
    assert "__interrupt__" not in out
    report = out["final_report"]
    agents = [r.agent for r in report.agent_reports]
    assert agents == ["news", "financials", "technicals", "valuation"]
    assert all(r.status == "ok" and r.claims for r in report.agent_reports)
    assert report.recommendation.stance == "bullish"
    assert report.lens == "growth"
    # Valuation consumed the financials agent's EDGAR figures (P/S claim).
    val = next(r for r in report.agent_reports if r.agent == "valuation")
    assert any("P/S" in c.claim or "revenue" in c.claim for c in val.claims)
    print("✓ deep dive runs all four agents + recommendation")


def test_quick_run_subset():
    g = make_graph()
    out = g.invoke({"run_id": "t2", "ticker": "AAPL", "depth": "quick"}, cfg("t2"))
    report = out["final_report"]
    agents = {r.agent for r in report.agent_reports}
    assert agents == {"technicals", "valuation"}
    assert "valuation_without_financials" in report.flags
    print("✓ quick check runs only technicals + valuation")


def test_clarifying_question_flow():
    g = make_graph()
    out = g.invoke({"run_id": "t3", "ticker": "MSFT"}, cfg("t3"))  # no depth
    assert "__interrupt__" in out
    q = out["__interrupt__"][0].value
    assert "quick" in q["options"] and "deep" in q["options"]
    # Answer "deep" → planner should next ask for a lens.
    out = g.invoke(Command(resume="deep"), cfg("t3"))
    assert "__interrupt__" in out
    assert "growth" in out["__interrupt__"][0].value["options"]
    out = g.invoke(Command(resume="value"), cfg("t3"))
    report = out["final_report"]
    assert report.depth == "deep" and report.lens == "value"
    assert len(report.agent_reports) == 4
    print("✓ planner pauses for depth + lens questions and resumes correctly")


def test_share_class_ambiguity():
    g = make_graph()
    out = g.invoke({"run_id": "t4", "ticker": "GOOG", "depth": "quick"}, cfg("t4"))
    assert "__interrupt__" in out
    assert "share class" in out["__interrupt__"][0].value["question"]
    out = g.invoke(Command(resume="GOOGL (Class A, voting)"), cfg("t4"))
    assert out["final_report"].ticker == "GOOGL"
    print("✓ ambiguous share class triggers a clarifying question")


def test_single_agent_failure_does_not_crash():
    g = make_graph(news=FailingNews())
    out = g.invoke({"run_id": "t5", "ticker": "TSLA", "depth": "deep",
                    "lens": "balanced"}, cfg("t5"))
    report = out["final_report"]
    news = next(r for r in report.agent_reports if r.agent == "news")
    assert news.status == "failed" and not news.claims
    assert "news_unavailable" in report.flags
    others = [r for r in report.agent_reports if r.agent != "news"]
    assert all(r.status == "ok" and r.claims for r in others)
    assert report.recommendation.summary  # synthesis still produced
    print("✓ news agent failure is flagged; run completes with other agents")


def test_recommendation_llm_failure_fallback():
    g = make_graph(llm=FailingAgentLLM())
    out = g.invoke({"run_id": "t6", "ticker": "NVDA", "depth": "quick"}, cfg("t6"))
    report = out["final_report"]
    assert "recommendation_llm_failed" in report.flags
    assert report.recommendation.stance == "neutral"
    assert report.agent_reports  # claims still delivered
    print("✓ recommendation LLM failure degrades to flagged fallback")


def test_app_routes():
    from app.main import app

    paths = {r.path for r in app.routes}
    for p in ("/research", "/research/{run_id}/events",
              "/research/{run_id}/answer", "/health"):
        assert p in paths, f"missing route {p}"
    print("✓ FastAPI routes wired (start / events / answer / health)")


if __name__ == "__main__":
    test_deep_run_all_agents()
    test_quick_run_subset()
    test_clarifying_question_flow()
    test_share_class_ambiguity()
    test_single_agent_failure_does_not_crash()
    test_recommendation_llm_failure_fallback()
    test_app_routes()
    print("\nAll Phase 2 tests passed.")
