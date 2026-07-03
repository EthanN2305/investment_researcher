"""Phase 3 tests — no API keys or network required (all tools are fakes).

Run: cd backend && python -m pytest tests/test_phase3.py -q
Covers: sign-up/login/JWT flow, portfolio & preferences CRUD (with per-user
scoping), the Portfolio Manager Agent's claim heuristics, and the personalized
graph run (portfolio agent joins the plan only when a portfolio_context is
supplied).
"""
from __future__ import annotations

import os
import tempfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base, get_db
from app.graph import build_graph
from app.models import (
    AgentReport,
    Claim,
    Financials,
    HoldingOut,
    MarketData,
    NewsItem,
    PortfolioContext,
    PreferencesOut,
    PriceHistory,
    Recommendation,
)
from app.agents.portfolio import PortfolioManagerAgent
from app.routers import auth_router, create_portfolio_router
from app.tools.base import ToolError


# --- Fakes --------------------------------------------------------------------
class FakeMarket:
    name = "fake-market"

    def __init__(self, sector="Technology", pe=40.0, price=100.0,
                 low=60.0, high=140.0):
        self.sector, self.pe, self.price, self.low, self.high = (
            sector, pe, price, low, high,
        )

    def get_market_data(self, ticker: str) -> MarketData:
        return MarketData(
            ticker=ticker, name="Fake Corp", price=self.price, currency="USD",
            market_cap=1_000_000_000, pe_ratio=self.pe, sector=self.sector,
            fifty_two_week_high=self.high, fifty_two_week_low=self.low,
        )


class FailingMarket:
    name = "failing-market"

    def get_market_data(self, ticker: str) -> MarketData:
        raise ToolError("simulated market outage")


class FakePrices:
    name = "fake-prices"

    def get_history(self, ticker: str, period: str = "1y") -> PriceHistory:
        closes = [100.0 + (i % 10) for i in range(250)]
        return PriceHistory(
            ticker=ticker,
            dates=[f"2026-{1 + i // 30:02d}-{1 + i % 28:02d}" for i in range(250)],
            closes=closes,
        )


class FakeEdgar:
    name = "fake-edgar"

    def get_financials(self, ticker: str) -> Financials:
        return Financials(ticker=ticker, revenue=500_000_000,
                          net_income=50_000_000, source="fake-edgar")


class FakeNews:
    name = "fake-news"

    def get_news(self, ticker: str, limit: int = 8) -> list[NewsItem]:
        return []


class FakeLLM:
    name = "fake-llm"

    def claims_from_news(self, ticker, news):
        return []

    def recommend(self, ticker, agent_reports, lens, flags) -> Recommendation:
        return Recommendation(
            summary=f"synth over {len(agent_reports)} agents", stance="neutral",
            confidence=0.6,
        )


def _context(holdings=None, prefs=None) -> PortfolioContext:
    return PortfolioContext(
        user_email="test@example.com",
        holdings=holdings or [],
        preferences=prefs,
    )


def _h(id_, ticker, qty, basis, sector) -> HoldingOut:
    return HoldingOut(id=id_, ticker=ticker, quantity=qty, cost_basis=basis,
                      sector=sector)


# --- API app under test ---------------------------------------------------------
@pytest.fixture()
def client():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    engine = create_engine(
        f"sqlite:///{path}", connect_args={"check_same_thread": False}
    )
    TestSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(engine)

    def override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app = FastAPI()
    app.include_router(auth_router)
    app.include_router(create_portfolio_router(FakeMarket()))
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    os.unlink(path)


def _signup(client, email="ethan@example.com", password="hunter2secure"):
    r = client.post("/auth/signup", json={"email": email, "password": password})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# --- Auth ----------------------------------------------------------------------
def test_signup_login_me(client):
    headers = _signup(client)
    assert client.get("/auth/me", headers=headers).json()["email"] == "ethan@example.com"

    # duplicate email
    r = client.post("/auth/signup",
                    json={"email": "ethan@example.com", "password": "hunter2secure"})
    assert r.status_code == 409

    # login good / bad
    r = client.post("/auth/login",
                    json={"email": "ethan@example.com", "password": "hunter2secure"})
    assert r.status_code == 200 and r.json()["access_token"]
    r = client.post("/auth/login",
                    json={"email": "ethan@example.com", "password": "wrong-password"})
    assert r.status_code == 401


def test_short_password_rejected(client):
    r = client.post("/auth/signup", json={"email": "a@b.co", "password": "short"})
    assert r.status_code == 422


def test_endpoints_require_auth(client):
    assert client.get("/portfolio").status_code == 401
    assert client.post("/portfolio",
                       json={"ticker": "AAPL", "quantity": 1, "cost_basis": 1}
                       ).status_code == 401
    assert client.get("/preferences").status_code == 401
    assert client.get("/auth/me", headers={"Authorization": "Bearer garbage"}
                      ).status_code == 401


# --- Portfolio & preferences CRUD ------------------------------------------------
def test_holding_crud_and_scoping(client):
    h1 = _signup(client, "u1@example.com")
    h2 = _signup(client, "u2@example.com")

    r = client.post("/portfolio", headers=h1,
                    json={"ticker": "aapl", "quantity": 10, "cost_basis": 150})
    assert r.status_code == 201
    body = r.json()
    assert body["ticker"] == "AAPL"  # normalized
    assert body["sector"] == "Technology"  # captured from market provider

    # upsert same ticker updates in place
    r = client.post("/portfolio", headers=h1,
                    json={"ticker": "AAPL", "quantity": 25, "cost_basis": 140})
    assert r.status_code == 201 and r.json()["quantity"] == 25
    assert len(client.get("/portfolio", headers=h1).json()) == 1

    # user 2 sees nothing, can't delete user 1's holding
    assert client.get("/portfolio", headers=h2).json() == []
    hid = client.get("/portfolio", headers=h1).json()[0]["id"]
    assert client.delete(f"/portfolio/{hid}", headers=h2).status_code == 404
    assert client.delete(f"/portfolio/{hid}", headers=h1).status_code == 204
    assert client.get("/portfolio", headers=h1).json() == []


def test_preferences_roundtrip_and_validation(client):
    headers = _signup(client)
    # empty default
    assert client.get("/preferences", headers=headers).json()["risk_tolerance"] is None

    r = client.put("/preferences", headers=headers, json={
        "risk_tolerance": "low", "sector_interests": ["Technology", "Energy"],
        "growth_value_lean": "value", "time_horizon": "long",
    })
    assert r.status_code == 200
    got = client.get("/preferences", headers=headers).json()
    assert got["risk_tolerance"] == "low"
    assert got["sector_interests"] == ["Technology", "Energy"]

    r = client.put("/preferences", headers=headers,
                   json={"risk_tolerance": "yolo"})
    assert r.status_code == 422


# --- Portfolio Manager Agent ------------------------------------------------------
def test_new_position_and_diversification():
    agent = PortfolioManagerAgent(FakeMarket(sector="Energy"))
    ctx = _context([_h(1, "AAPL", 10, 150, "Technology")])
    report = agent.run("XOM", ctx)
    texts = " ".join(c.claim for c in report.claims)
    assert report.status == "ok"
    assert "new position" in texts
    assert "diversify" in texts


def test_concentration_and_sector_overlap():
    agent = PortfolioManagerAgent(FakeMarket(sector="Technology"))
    ctx = _context([
        _h(1, "AAPL", 10, 150, "Technology"),   # 1500 → 60% of cost value
        _h(2, "MSFT", 2, 300, "Technology"),    # 600
        _h(3, "XOM", 4, 100, "Energy"),         # 400
    ])
    report = agent.run("AAPL", ctx)
    texts = " ".join(c.claim for c in report.claims)
    assert "Concentration risk" in texts
    assert "Sector overlap" in texts  # MSFT overlaps in Technology
    assert all(c.source == "User portfolio & stated preferences"
               for c in report.claims)
    assert all(0.0 <= c.confidence <= 1.0 for c in report.claims)


def test_preference_mismatch_claims():
    # value lean vs P/E 40, low risk vs wide 52-week range
    agent = PortfolioManagerAgent(FakeMarket(pe=40.0, price=100, low=60, high=140))
    prefs = PreferencesOut(risk_tolerance="low", growth_value_lean="value",
                           sector_interests=["Technology"], time_horizon="short")
    report = agent.run("NVDA", _context([_h(1, "KO", 10, 60, "Consumer")], prefs))
    texts = " ".join(c.claim for c in report.claims)
    assert "value lean" in texts
    assert "52-week range" in texts
    assert "sector interests" in texts
    assert "time horizon is short" in texts


def test_empty_portfolio_flags():
    agent = PortfolioManagerAgent(FakeMarket())
    report = agent.run("AAPL", _context())
    assert "empty_portfolio" in report.flags
    assert "no_stated_preferences" in report.flags


def test_market_outage_still_produces_holding_claims():
    agent = PortfolioManagerAgent(FailingMarket())
    report = agent.run("AAPL", _context([_h(1, "AAPL", 10, 150, "Technology")]))
    assert report.status == "ok"
    assert "portfolio_no_market_data" in report.flags
    assert any("already hold" in c.claim for c in report.claims)


# --- Personalized graph run --------------------------------------------------------
def _graph():
    return build_graph(
        market=FakeMarket(), news=FakeNews(), financials=FakeEdgar(),
        prices=FakePrices(), llm=FakeLLM(),
    )


def _invoke(graph, payload):
    return graph.invoke(payload, {"configurable": {"thread_id": payload["run_id"]}})


def test_generic_run_has_no_portfolio_agent():
    result = _invoke(_graph(), {"run_id": "t1", "ticker": "AAPL", "depth": "quick"})
    report = result["final_report"]
    assert "portfolio" not in [r.agent for r in report.agent_reports]


def test_personalized_run_includes_portfolio_agent():
    ctx = _context(
        [_h(1, "AAPL", 10, 150, "Technology")],
        PreferencesOut(risk_tolerance="medium"),
    ).model_dump()
    result = _invoke(_graph(), {
        "run_id": "t2", "ticker": "AAPL", "depth": "quick",
        "portfolio_context": ctx,
    })
    report = result["final_report"]
    agents = [r.agent for r in report.agent_reports]
    assert "portfolio" in agents
    port = next(r for r in report.agent_reports if r.agent == "portfolio")
    assert port.status == "ok" and port.claims
    # portfolio runs after valuation, before recommendation (plan order kept)
    assert agents.index("portfolio") > agents.index("valuation")


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-q"]))
