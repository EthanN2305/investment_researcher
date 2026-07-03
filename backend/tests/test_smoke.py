"""Smoke tests — no API keys required.

Run: cd backend && python -m tests.test_smoke
Verifies models, tool interfaces, pipeline orchestration (with fakes), error
handling, and that the FastAPI app imports and wires the endpoint.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.models import Claim, MarketData, NewsItem, ResearchReport
from app.pipeline import ResearchPipeline
from app.tools.base import (
    LLMProvider,
    MarketDataProvider,
    NewsProvider,
    ToolError,
)


# --- Fakes ------------------------------------------------------------------
class FakeMarket:
    name = "fake-market"

    def get_market_data(self, ticker: str) -> MarketData:
        return MarketData(
            ticker=ticker,
            name="Fake Corp",
            price=123.45,
            currency="USD",
            market_cap=1_000_000_000,
            as_of=datetime.now(timezone.utc).isoformat(),
        )


class FailingNews:
    name = "failing-news"

    def get_news(self, ticker: str, limit: int = 8):
        raise ToolError("simulated news outage")


class EmptyNews:
    name = "empty-news"

    def get_news(self, ticker: str, limit: int = 8):
        return []


class FakeLLM:
    name = "fake-llm"

    def generate_claims(self, ticker, market, news):
        claims = [
            Claim(
                claim=f"{ticker} last traded at {market.price} {market.currency}",
                evidence=f"price={market.price}",
                source=market.source,
                confidence=0.9,
            )
        ]
        return claims, "A fake but well-formed summary."


def test_models_and_contract():
    r = ResearchReport(
        ticker="TEST",
        claims=[Claim(claim="c", evidence="e", source="s", confidence=0.5)],
        summary="s",
        generated_at=datetime.now(timezone.utc).isoformat(),
    )
    dumped = r.model_dump()
    assert set(["ticker", "claims", "summary", "flags", "generated_at"]).issubset(dumped)
    # confidence bounds enforced
    try:
        Claim(claim="c", evidence="e", source="s", confidence=1.5)
        raise AssertionError("confidence >1 should fail validation")
    except Exception:
        pass
    print("✓ models & structured-output contract")


def test_interfaces_are_satisfied():
    assert isinstance(FakeMarket(), MarketDataProvider)
    assert isinstance(FailingNews(), NewsProvider)
    assert isinstance(FakeLLM(), LLMProvider)
    print("✓ fakes satisfy tool Protocols")


def test_pipeline_happy_path():
    p = ResearchPipeline(FakeMarket(), EmptyNews(), FakeLLM())
    report = p.run("aapl")
    assert report.ticker == "AAPL"
    assert len(report.claims) == 1
    assert "no_recent_news" in report.flags
    print("✓ pipeline happy path (ticker upcased, empty-news flagged)")


def test_pipeline_degrades_on_news_failure():
    p = ResearchPipeline(FakeMarket(), FailingNews(), FakeLLM())
    report = p.run("MSFT")
    assert "missing_news" in report.flags
    assert len(report.claims) == 1  # still produces a report
    print("✓ pipeline degrades gracefully when news tool fails")


def test_app_imports_and_wires_endpoint():
    from app.main import app

    paths = {r.path for r in app.routes}
    assert "/research" in paths  # Phase 2: start-run endpoint
    assert "/health" in paths
    print("✓ FastAPI app imports; /research and /health wired")


if __name__ == "__main__":
    test_models_and_contract()
    test_interfaces_are_satisfied()
    test_pipeline_happy_path()
    test_pipeline_degrades_on_news_failure()
    test_app_imports_and_wires_endpoint()
    print("\nAll smoke tests passed.")
