"""Phase 4 tests — no API keys or network required (all tools are fakes).

Run: cd backend && python -m pytest tests/test_phase4.py -q
Covers: watchlist CRUD + scoping, the headless daily-summary run (stored
reports, short summaries, feed endpoints, run-now), alert-rule config +
evaluation (price move / new high-confidence claim / negative news),
notification endpoints, email console fallback, and the derived (reasoned)
recommendation confidence.
"""
from __future__ import annotations

import os
import tempfile
import time
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.agents.recommend import derive_confidence
from app.alerts_engine import evaluate_rules, latest_price_move_pct
from app.db import Base, get_db
from app.db_models import AlertRule, Notification, StoredReport, User
from app.graph import build_graph
from app.models import (
    AgentReport,
    Claim,
    FinalReport,
    Financials,
    MarketData,
    NewsItem,
    PriceHistory,
    Recommendation,
)
from app.db_models import EmailDigestPreference
from app.digest import build_digest, is_due, send_digest_for_user
from app.routers import (
    alerts_router,
    auth_router,
    create_portfolio_router,
    create_summaries_router,
    digest_router,
    watchlist_router,
)
from app.summaries import short_summary, tickers_for_user
from app.tools.base import ToolError


# --- Fakes (same style as Phase 3) ---------------------------------------------
class FakeMarket:
    name = "fake-market"

    def get_market_data(self, ticker: str) -> MarketData:
        return MarketData(
            ticker=ticker, name="Fake Corp", price=100.0, currency="USD",
            market_cap=1_000_000_000, pe_ratio=25.0, sector="Technology",
            fifty_two_week_high=140.0, fifty_two_week_low=60.0,
        )


class FakePrices:
    name = "fake-prices"

    def __init__(self, closes=None):
        self.closes = closes or [100.0 + (i % 10) for i in range(250)]

    def get_history(self, ticker: str, period: str = "1y") -> PriceHistory:
        return PriceHistory(
            ticker=ticker,
            dates=[f"2026-{1 + i // 30:02d}-{1 + i % 28:02d}"
                   for i in range(len(self.closes))],
            closes=self.closes,
        )


class FailingPrices:
    name = "failing-prices"

    def get_history(self, ticker: str, period: str = "1y") -> PriceHistory:
        raise ToolError("simulated price outage")


class FakeEdgar:
    name = "fake-edgar"

    def get_financials(self, ticker: str) -> Financials:
        return Financials(ticker=ticker, revenue=500_000_000,
                          net_income=50_000_000, source="fake-edgar")


class FakeNews:
    name = "fake-news"

    def __init__(self, items=None):
        self.items = items or []

    def get_news(self, ticker: str, limit: int = 8) -> list[NewsItem]:
        return self.items


class FakeLLM:
    name = "fake-llm"

    def __init__(self, news_claims=None):
        self.news_claims = news_claims or []

    def claims_from_news(self, ticker, news):
        return self.news_claims

    def recommend(self, ticker, agent_reports, lens, flags) -> Recommendation:
        return Recommendation(
            summary="First sentence. Second sentence. Third sentence. Fourth.",
            stance="bullish", confidence=0.7,
        )


def _claim(text, conf=0.8, source="src", evidence="ev") -> Claim:
    return Claim(claim=text, evidence=evidence, source=source, confidence=conf)


def _report(ticker="AAPL", agent_claims=None) -> FinalReport:
    """agent_claims: dict of agent -> list[Claim]"""
    reports = [
        AgentReport(agent=a, claims=cs)
        for a, cs in (agent_claims or {}).items()
    ]
    return FinalReport(
        ticker=ticker, agent_reports=reports,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


def _rule(condition, threshold=None, active=True, email=False) -> AlertRule:
    return AlertRule(user_id=1, ticker="AAPL", condition=condition,
                     threshold=threshold, active=active, email=email)


# --- App under test ---------------------------------------------------------------
@pytest.fixture()
def api():
    """(client, SessionLocal) with the full Phase 3+4 router set and fake graph."""
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

    graph = build_graph(
        market=FakeMarket(), news=FakeNews(), financials=FakeEdgar(),
        prices=FakePrices(), llm=FakeLLM(),
    )
    app = FastAPI()
    app.include_router(auth_router)
    app.include_router(create_portfolio_router(FakeMarket()))
    app.include_router(watchlist_router)
    # session_factory: run-now worker threads must hit the test DB
    app.include_router(create_summaries_router(graph, FakePrices(), TestSession))
    app.include_router(alerts_router)
    app.include_router(digest_router)
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c, TestSession
    os.unlink(path)


def _signup(client, email="ethan@example.com", password="hunter2secure"):
    r = client.post("/auth/signup", json={"email": email, "password": password})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _run_now_and_wait(client, headers, timeout=10.0, mode=None):
    """Start a run-now job and poll its progress endpoint until done."""
    url = "/summaries/run" + (f"?mode={mode}" if mode else "")
    r = client.post(url, headers=headers)
    assert r.status_code == 202, r.text
    job = r.json()
    assert job["status"] in ("running", "done")
    deadline = time.time() + timeout
    while job["status"] == "running" and time.time() < deadline:
        time.sleep(0.05)
        r = client.get(f"/summaries/run/{job['job_id']}", headers=headers)
        assert r.status_code == 200, r.text
        job = r.json()
    assert job["status"] == "done", job
    assert job["completed"] == job["total"]
    return job


# --- Watchlist -------------------------------------------------------------------
def test_watchlist_requires_auth(api):
    client, _ = api
    assert client.get("/watchlist").status_code == 401
    assert client.post("/watchlist", json={"ticker": "AAPL"}).status_code == 401


def test_watchlist_crud_and_scoping(api):
    client, _ = api
    h1 = _signup(client, "u1@example.com")
    h2 = _signup(client, "u2@example.com")

    r = client.post("/watchlist", headers=h1,
                    json={"ticker": "nvda", "note": "watching for dip"})
    assert r.status_code == 201
    assert r.json()["ticker"] == "NVDA"  # normalized

    # idempotent upsert — same ticker doesn't duplicate, note refreshes
    r = client.post("/watchlist", headers=h1,
                    json={"ticker": "NVDA", "note": "still watching"})
    assert r.status_code == 201
    items = client.get("/watchlist", headers=h1).json()
    assert len(items) == 1 and items[0]["note"] == "still watching"

    # invalid ticker rejected
    assert client.post("/watchlist", headers=h1,
                       json={"ticker": "NOT A TICKER!"}).status_code == 422

    # scoping: user 2 sees nothing and can't delete user 1's item
    assert client.get("/watchlist", headers=h2).json() == []
    item_id = items[0]["id"]
    assert client.delete(f"/watchlist/{item_id}", headers=h2).status_code == 404
    assert client.delete(f"/watchlist/{item_id}", headers=h1).status_code == 204
    assert client.get("/watchlist", headers=h1).json() == []


def test_tickers_for_user_merges_watchlist_and_holdings(api):
    client, TestSession = api
    headers = _signup(client)
    client.post("/watchlist", headers=headers, json={"ticker": "NVDA"})
    client.post("/watchlist", headers=headers, json={"ticker": "AAPL"})
    client.post("/portfolio", headers=headers,
                json={"ticker": "AAPL", "quantity": 5, "cost_basis": 150})
    db = TestSession()
    try:
        user = db.scalar(select(User))
        assert tickers_for_user(db, user) == ["AAPL", "NVDA"]  # deduped, sorted
    finally:
        db.close()


# --- Daily summaries ---------------------------------------------------------------
def test_run_now_requires_tickers(api):
    client, _ = api
    headers = _signup(client)
    assert client.post("/summaries/run", headers=headers).status_code == 422


def test_run_now_stores_and_lists_summaries(api):
    client, _ = api
    headers = _signup(client)
    client.post("/watchlist", headers=headers, json={"ticker": "AAPL"})

    job = _run_now_and_wait(client, headers)
    assert job["total"] == 1 and job["tickers"] == ["AAPL"]
    stored = job["results"]
    assert len(stored) == 1
    assert stored[0]["ticker"] == "AAPL"
    assert stored[0]["trigger"] == "manual"
    assert stored[0]["stance"] == "bullish"
    assert stored[0]["summary"].startswith("First sentence.")
    # short summary keeps only the first few sentences
    assert "Fourth" not in stored[0]["summary"]

    feed = client.get("/summaries", headers=headers).json()
    assert len(feed) == 1

    # full report is retrievable without re-running agents
    full = client.get(f"/summaries/{feed[0]['id']}", headers=headers)
    assert full.status_code == 200
    report = full.json()["report"]
    agents = [a["agent"] for a in report["agent_reports"]]
    assert "technicals" in agents and "valuation" in agents
    assert report["recommendation"]["confidence_rationale"]

    # scoping: another user can't read the summary or poll the job
    h2 = _signup(client, "u2@example.com")
    assert client.get(f"/summaries/{feed[0]['id']}", headers=h2).status_code == 404
    assert client.get(f"/summaries/run/{job['job_id']}", headers=h2
                      ).status_code == 404


def test_run_now_missing_mode_only_runs_new_tickers(api):
    """mode=missing skips tickers already summarized today — a second click
    after adding one holding runs agents for that holding only (no wasted
    tokens), and an all-fresh feed spawns no job at all."""
    client, _ = api
    headers = _signup(client)
    client.post("/watchlist", headers=headers, json={"ticker": "MU"})

    job = _run_now_and_wait(client, headers, mode="missing")
    assert job["tickers"] == ["MU"]

    # add a holding after the first run — only the new ticker is researched
    client.post("/watchlist", headers=headers, json={"ticker": "NVDA"})
    job = _run_now_and_wait(client, headers, mode="missing")
    assert job["tickers"] == ["NVDA"]

    # everything fresh → nothing runs, no job spawned
    r = client.post("/summaries/run?mode=missing", headers=headers)
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "done"
    assert body["total"] == 0 and body["job_id"] is None

    # rerun-all still sweeps everything (default mode stays 'all')
    job = _run_now_and_wait(client, headers, mode="all")
    assert job["tickers"] == ["MU", "NVDA"]


def test_summaries_latest_dedupes_to_newest_per_ticker(api):
    """latest=true returns one (newest) row per ticker; history remains
    available without the flag."""
    client, _ = api
    headers = _signup(client)
    client.post("/watchlist", headers=headers, json={"ticker": "MU"})
    _run_now_and_wait(client, headers, mode="all")
    _run_now_and_wait(client, headers, mode="all")

    full = client.get("/summaries", headers=headers).json()
    assert len(full) == 2  # history keeps both runs

    latest = client.get("/summaries?latest=true", headers=headers).json()
    assert len(latest) == 1
    assert latest[0]["ticker"] == "MU"
    assert latest[0]["id"] == max(s["id"] for s in full)


def test_scheduled_sweep_covers_all_users(api):
    """The scheduler entrypoint stores reports for every user's tickers."""
    from app import scheduler as sched_mod

    client, TestSession = api
    h1 = _signup(client, "u1@example.com")
    h2 = _signup(client, "u2@example.com")
    client.post("/watchlist", headers=h1, json={"ticker": "AAPL"})
    client.post("/watchlist", headers=h2, json={"ticker": "MSFT"})

    graph = build_graph(
        market=FakeMarket(), news=FakeNews(), financials=FakeEdgar(),
        prices=FakePrices(), llm=FakeLLM(),
    )
    # point the sweep at the test DB
    original = sched_mod.SessionLocal
    sched_mod.SessionLocal = TestSession
    try:
        count = sched_mod.run_daily_summaries(graph, FakePrices())
    finally:
        sched_mod.SessionLocal = original
    assert count == 2

    db = TestSession()
    try:
        rows = db.scalars(select(StoredReport)).all()
        assert sorted(r.ticker for r in rows) == ["AAPL", "MSFT"]
        assert all(r.trigger == "scheduled" for r in rows)
    finally:
        db.close()


def test_short_summary_fallback_when_llm_summary_empty():
    report = _report(agent_claims={"technicals": [_claim("t1"), _claim("t2")]})
    assert "2 claims" in short_summary(report)


# --- Alert evaluation (pure logic) ---------------------------------------------------
def test_price_move_alert_fires_on_threshold():
    report = _report()
    fired = evaluate_rules(
        ticker="AAPL", rules=[_rule("price_move", threshold=5.0)],
        report=report, previous_report=None, price_move_pct=-6.2,
    )
    assert len(fired) == 1
    assert fired[0].condition == "price_move"
    assert "down 6.2%" in fired[0].title

    # below threshold → silent
    assert evaluate_rules(
        ticker="AAPL", rules=[_rule("price_move", threshold=5.0)],
        report=report, previous_report=None, price_move_pct=4.9,
    ) == []


def test_price_move_uses_default_threshold_and_handles_missing_price():
    report = _report()
    # default threshold is 5% — a 5.5% move fires with threshold=None
    fired = evaluate_rules(
        ticker="AAPL", rules=[_rule("price_move")], report=report,
        previous_report=None, price_move_pct=5.5,
    )
    assert len(fired) == 1
    # no price data → no crash, no alert
    assert evaluate_rules(
        ticker="AAPL", rules=[_rule("price_move")], report=report,
        previous_report=None, price_move_pct=None,
    ) == []


def test_high_confidence_claim_fires_only_when_new():
    prev = _report(agent_claims={"financials": [_claim("Revenue grew 20%", 0.95)]})
    new = _report(agent_claims={
        "financials": [
            _claim("Revenue grew 20%", 0.95),      # already known — no re-fire
            _claim("Margins hit a record", 0.9),   # new — fires
        ]
    })
    fired = evaluate_rules(
        ticker="AAPL", rules=[_rule("high_confidence_claim", threshold=0.85)],
        report=new, previous_report=prev, price_move_pct=None,
    )
    assert len(fired) == 1
    assert "Margins hit a record" in fired[0].body

    # nothing new above threshold → silent
    assert evaluate_rules(
        ticker="AAPL", rules=[_rule("high_confidence_claim", threshold=0.85)],
        report=prev, previous_report=prev, price_move_pct=None,
    ) == []


def test_negative_news_alert_keyword_heuristic():
    new = _report(agent_claims={
        "news": [
            _claim("Company faces a class-action lawsuit over data practices", 0.7),
            _claim("Product launch was well received", 0.8),
        ]
    })
    fired = evaluate_rules(
        ticker="AAPL", rules=[_rule("negative_news")],
        report=new, previous_report=None, price_move_pct=None,
    )
    assert len(fired) == 1
    assert fired[0].condition == "negative_news"
    assert "lawsuit" in fired[0].body

    # non-news agents never trigger negative_news
    only_technicals = _report(agent_claims={
        "technicals": [_claim("Price dropped below the 50-day SMA", 0.9)]
    })
    assert evaluate_rules(
        ticker="AAPL", rules=[_rule("negative_news")],
        report=only_technicals, previous_report=None, price_move_pct=None,
    ) == []


def test_inactive_rule_never_fires():
    assert evaluate_rules(
        ticker="AAPL", rules=[_rule("price_move", threshold=1.0, active=False)],
        report=_report(), previous_report=None, price_move_pct=50.0,
    ) == []


def test_latest_price_move_pct():
    assert latest_price_move_pct(FakePrices([100.0, 110.0]), "X") == pytest.approx(10.0)
    assert latest_price_move_pct(FakePrices([100.0]), "X") is None
    assert latest_price_move_pct(FailingPrices(), "X") is None


# --- Alerts API + notifications end-to-end -------------------------------------------
def test_alert_rule_crud_and_validation(api):
    client, _ = api
    headers = _signup(client)

    r = client.post("/alerts", headers=headers,
                    json={"ticker": "aapl", "condition": "price_move",
                          "threshold": 3.0})
    assert r.status_code == 201 and r.json()["ticker"] == "AAPL"

    # upsert same (ticker, condition) updates in place
    r = client.post("/alerts", headers=headers,
                    json={"ticker": "AAPL", "condition": "price_move",
                          "threshold": 7.5, "email": True})
    assert r.status_code == 201
    rules = client.get("/alerts", headers=headers).json()
    assert len(rules) == 1 and rules[0]["threshold"] == 7.5 and rules[0]["email"]

    # validation
    assert client.post("/alerts", headers=headers,
                       json={"ticker": "AAPL", "condition": "moon_phase"}
                       ).status_code == 422
    assert client.post("/alerts", headers=headers,
                       json={"ticker": "AAPL", "condition": "price_move",
                             "threshold": 500}).status_code == 422
    assert client.post("/alerts", headers=headers,
                       json={"ticker": "AAPL",
                             "condition": "high_confidence_claim",
                             "threshold": 5}).status_code == 422

    assert client.delete(f"/alerts/{rules[0]['id']}", headers=headers
                         ).status_code == 204
    assert client.get("/alerts", headers=headers).json() == []


def test_summary_run_fires_alerts_and_notifications_flow(api, caplog):
    """End-to-end: watchlist + rule → run-now → notification appears (and the
    email stretch logs its console fallback)."""
    client, _ = api
    headers = _signup(client)
    client.post("/watchlist", headers=headers, json={"ticker": "AAPL"})
    # FakeLLM's recommendation isn't a claim; technicals/valuation claims from
    # the fake tools carry confidence ≥ threshold → fires on first run.
    client.post("/alerts", headers=headers,
                json={"ticker": "AAPL", "condition": "high_confidence_claim",
                      "threshold": 0.5, "email": True})

    import logging
    with caplog.at_level(logging.INFO, logger="notify"):
        _run_now_and_wait(client, headers)

    notes = client.get("/notifications", headers=headers).json()
    assert len(notes) >= 1
    note = notes[0]
    assert note["ticker"] == "AAPL" and not note["read"]
    assert note["condition"] == "high_confidence_claim"
    assert note["report_id"] is not None
    # email stretch: console fallback logged (no SMTP configured in tests)
    assert any("console fallback" in m for m in caplog.messages)

    # unread count → mark read → count drops
    assert client.get("/notifications/unread-count", headers=headers
                      ).json()["unread"] >= 1
    r = client.post(f"/notifications/{note['id']}/read", headers=headers)
    assert r.status_code == 200 and r.json()["read"]
    client.post("/notifications/read-all", headers=headers)
    assert client.get("/notifications/unread-count", headers=headers
                      ).json()["unread"] == 0

    # second identical run: claims are no longer "new" → no duplicate alert
    _run_now_and_wait(client, headers)
    assert client.get("/notifications/unread-count", headers=headers
                      ).json()["unread"] == 0


def test_notifications_scoped_per_user(api):
    client, TestSession = api
    h1 = _signup(client, "u1@example.com")
    h2 = _signup(client, "u2@example.com")
    db = TestSession()
    try:
        u1 = db.scalar(select(User).where(User.email == "u1@example.com"))
        db.add(Notification(user_id=u1.id, ticker="AAPL",
                            condition="price_move", title="t"))
        db.commit()
    finally:
        db.close()
    assert len(client.get("/notifications", headers=h1).json()) == 1
    assert client.get("/notifications", headers=h2).json() == []


# --- Email digest ---------------------------------------------------------------------
def _pref(enabled=True, frequency="daily", weekday=None, last_sent_at=None):
    return EmailDigestPreference(
        user_id=1, enabled=enabled, frequency=frequency,
        weekday=weekday, last_sent_at=last_sent_at,
    )


def test_digest_is_due_daily_weekly_monthly():
    monday = datetime(2026, 7, 6, 14, 0)      # a Monday, not the 1st
    first = datetime(2026, 7, 1, 14, 0)       # 1st of the month (a Wednesday)

    assert is_due(None, monday) is False                      # no prefs row
    assert is_due(_pref(enabled=False), monday) is False      # disabled

    assert is_due(_pref(frequency="daily"), monday) is True
    assert is_due(_pref(frequency="weekly", weekday=0), monday) is True
    assert is_due(_pref(frequency="weekly", weekday=4), monday) is False
    assert is_due(_pref(frequency="weekly"), monday) is True  # weekday defaults Mon
    assert is_due(_pref(frequency="monthly"), first) is True
    assert is_due(_pref(frequency="monthly"), monday) is False

    # dedupe: already sent today → never resend
    assert is_due(
        _pref(frequency="daily", last_sent_at=monday.replace(hour=6)), monday
    ) is False
    # sent yesterday → due again
    assert is_due(
        _pref(frequency="daily", last_sent_at=datetime(2026, 7, 5, 6, 0)), monday
    ) is True


def test_build_digest_body():
    now = datetime(2026, 7, 4, 13, 30)
    rows = [
        StoredReport(user_id=1, ticker="AAPL", stance="bullish",
                     confidence=0.72, summary="Looks strong.", report_json="{}"),
        StoredReport(user_id=1, ticker="NVDA", stance="bearish",
                     confidence=0.4, summary="Cooling off.", report_json="{}"),
    ]
    subject, body = build_digest(rows, now)
    assert "July 4, 2026" in subject
    assert "2 ticker(s)" in body
    assert "AAPL — BULLISH (72% confidence)" in body
    assert "Cooling off." in body
    assert "not investment advice" in body


def test_digest_prefs_api_roundtrip_and_validation(api):
    client, _ = api
    headers = _signup(client)

    # defaults: disabled
    got = client.get("/digest", headers=headers).json()
    assert got["enabled"] is False and got["frequency"] == "daily"

    # weekly requires a weekday
    r = client.put("/digest", headers=headers,
                   json={"enabled": True, "frequency": "weekly"})
    assert r.status_code == 422
    r = client.put("/digest", headers=headers,
                   json={"enabled": True, "frequency": "weekly", "weekday": 9})
    assert r.status_code == 422
    r = client.put("/digest", headers=headers,
                   json={"enabled": True, "frequency": "fortnightly"})
    assert r.status_code == 422

    r = client.put("/digest", headers=headers,
                   json={"enabled": True, "frequency": "weekly", "weekday": 4})
    assert r.status_code == 200
    got = client.get("/digest", headers=headers).json()
    assert got == {"enabled": True, "frequency": "weekly", "weekday": 4,
                   "last_sent_at": None}

    # switching to monthly clears the weekday
    client.put("/digest", headers=headers,
               json={"enabled": True, "frequency": "monthly", "weekday": 4})
    assert client.get("/digest", headers=headers).json()["weekday"] is None

    # auth required
    assert client.get("/digest").status_code == 401


def test_digest_send_now_and_scheduler_integration(api, caplog):
    """send-now emails the latest feed (console fallback in dev) and stamps
    last_sent_at; the sweep then skips re-sending the same day."""
    from app import scheduler as sched_mod

    client, TestSession = api
    headers = _signup(client)

    # nothing to digest yet → 422
    assert client.post("/digest/send-now", headers=headers).status_code == 422

    client.post("/watchlist", headers=headers, json={"ticker": "AAPL"})
    _run_now_and_wait(client, headers)
    client.put("/digest", headers=headers,
               json={"enabled": True, "frequency": "daily"})

    import logging
    with caplog.at_level(logging.INFO, logger="notify"):
        r = client.post("/digest/send-now", headers=headers)
    assert r.status_code == 200 and r.json()["sent"] is True
    assert any("Your investment digest" in m for m in caplog.messages)
    assert client.get("/digest", headers=headers).json()["last_sent_at"]

    # same-day sweep: summaries stored but digest deduped (already sent today)
    graph = build_graph(
        market=FakeMarket(), news=FakeNews(), financials=FakeEdgar(),
        prices=FakePrices(), llm=FakeLLM(),
    )
    caplog.clear()
    original = sched_mod.SessionLocal
    sched_mod.SessionLocal = TestSession
    try:
        with caplog.at_level(logging.INFO, logger="notify"):
            sched_mod.run_daily_summaries(graph, FakePrices())
    finally:
        sched_mod.SessionLocal = original
    assert not any("Your investment digest" in m for m in caplog.messages)

    # yesterday's send → sweep does email the digest
    db = TestSession()
    try:
        pref = db.scalar(select(EmailDigestPreference))
        pref.last_sent_at = datetime(2020, 1, 1)
        db.commit()
    finally:
        db.close()
    caplog.clear()
    sched_mod.SessionLocal = TestSession
    try:
        with caplog.at_level(logging.INFO, logger="notify"):
            sched_mod.run_daily_summaries(graph, FakePrices())
    finally:
        sched_mod.SessionLocal = original
    assert any("Your investment digest" in m for m in caplog.messages)


def test_digest_respects_weekly_schedule_in_send_flow(api):
    """A weekly digest not due today is skipped by the due-based sender."""
    client, TestSession = api
    headers = _signup(client)
    client.post("/watchlist", headers=headers, json={"ticker": "AAPL"})
    _run_now_and_wait(client, headers)

    # pick a weekday that is NOT today
    today = datetime.now(timezone.utc).weekday()
    other_day = (today + 3) % 7
    client.put("/digest", headers=headers,
               json={"enabled": True, "frequency": "weekly",
                     "weekday": other_day})

    db = TestSession()
    try:
        user = db.scalar(select(User))
        assert send_digest_for_user(db, user) is False          # not due
        assert send_digest_for_user(db, user, force=True) is True  # preview works
    finally:
        db.close()


# --- Derived (reasoned) confidence ----------------------------------------------------
def test_derived_confidence_is_not_flat_average():
    reports = [
        AgentReport(agent="financials", claims=[_claim("a", 0.9), _claim("b", 0.9)]),
        AgentReport(agent="news", claims=[_claim("c", 0.5)]),
    ]
    overall, per_agent, rationale = derive_confidence(reports, llm_confidence=0.7)
    flat = (0.9 + 0.9 + 0.5) / 3
    assert overall != pytest.approx(flat, abs=1e-6)
    assert per_agent == {"financials": 0.9, "news": 0.5}
    assert "Weighted evidence confidence" in rationale
    assert "disagreement" in rationale.lower()  # 0.4 spread noted


def test_failed_agents_lower_confidence():
    ok = [AgentReport(agent="financials", claims=[_claim("a", 0.8)]),
          AgentReport(agent="technicals", claims=[_claim("b", 0.8)])]
    with_failure = ok + [AgentReport(agent="news", status="failed", claims=[])]
    conf_ok, _, _ = derive_confidence(ok, llm_confidence=0.7)
    conf_fail, _, rationale = derive_confidence(with_failure, llm_confidence=0.7)
    assert conf_fail < conf_ok
    assert "missing coverage" in rationale


def test_no_claims_yields_minimal_confidence():
    overall, per_agent, _ = derive_confidence(
        [AgentReport(agent="news", status="failed")], llm_confidence=None
    )
    assert overall == 0.1 and per_agent == {}


def test_confidence_stays_in_bounds():
    high = [AgentReport(agent="financials", claims=[_claim("a", 1.0)] * 5)]
    low = [AgentReport(agent="news", claims=[_claim("a", 0.0)])]
    assert derive_confidence(high, 1.0)[0] <= 0.95
    assert derive_confidence(low, 0.0)[0] >= 0.05


def test_pipeline_report_carries_confidence_breakdown():
    graph = build_graph(
        market=FakeMarket(), news=FakeNews(), financials=FakeEdgar(),
        prices=FakePrices(), llm=FakeLLM(),
    )
    result = graph.invoke(
        {"run_id": "p4", "ticker": "AAPL", "depth": "quick"},
        {"configurable": {"thread_id": "p4"}},
    )
    rec = result["final_report"].recommendation
    assert rec.agent_confidences  # per-agent breakdown present
    assert rec.confidence_rationale
    assert 0.05 <= rec.confidence <= 0.95


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-q"]))
