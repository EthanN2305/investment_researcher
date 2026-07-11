"""Learn-tab v6: LLM news deep-dive, brief API budget, narration beats."""
from datetime import date
from types import SimpleNamespace

import pytest

from app import learn_news
from app.models import NewsItem


# --- helpers -----------------------------------------------------------------

def _fake_client(payload, calls, fail=False):
    """A stand-in Anthropic client: records calls, returns a forced tool block."""
    block = SimpleNamespace(type="tool_use", name="emit_video_news", input=payload)
    resp = SimpleNamespace(content=[block])

    class _Messages:
        def create(self, **kwargs):
            calls.append(kwargs)
            if fail:
                raise RuntimeError("provider down")
            return resp

    return SimpleNamespace(messages=_Messages())


PAYLOAD = {
    "stories": [
        {
            "headline": "Chipmaker beats on Q2 earnings",
            "what_happened": "Quarterly revenue came in at $8.1B, up 38% year over "
                             "year, ahead of Wall Street estimates.",
            "price_impact": "Beats like this usually push the stock higher because "
                            "analysts raise their forecasts.",
            "sentiment": "positive",
            "date": "2026-07-10",
        }
    ],
    "sentiment_score": 0.6,
    "sentiment_label": "Leaning bullish",
    "consumer_take": "Retail investors are hyped about the AI demand story.",
}

NEWS = [
    NewsItem(title="Chipmaker beats on Q2 earnings", url="https://x.test/1",
             source="Reuters", published_at="2026-07-10T12:00:00Z",
             summary="Revenue of $8.1B beat estimates."),
    NewsItem(title="Sector roundup", url="https://x.test/2", source="Blog",
             published_at="2026-07-09T09:00:00Z", summary="General market chatter."),
]

TODAY = date(2026, 7, 11)


@pytest.fixture(autouse=True)
def _fresh_news_cache():
    learn_news.clear_cache()
    yield
    learn_news.clear_cache()


# --- analyze_news --------------------------------------------------------------

def test_analyze_news_shapes_output():
    calls = []
    out = learn_news.analyze_news(
        "MU", "Micron", 100.0, 0.22, NEWS,
        client=_fake_client(PAYLOAD, calls), today=TODAY)
    assert len(calls) == 1
    assert out["stories"][0]["headline"] == "Chipmaker beats on Q2 earnings"
    assert out["stories"][0]["sentiment"] == "positive"
    assert out["sentiment_score"] == 0.6
    assert out["sentiment_label"] == "Leaning bullish"
    # Forced tool call, small budget.
    assert calls[0]["tool_choice"] == {"type": "tool", "name": "emit_video_news"}
    assert calls[0]["max_tokens"] <= 700


def test_analyze_news_caps_lengths_and_clamps_score():
    calls = []
    noisy = {
        "stories": [{
            "headline": "H" * 300,
            "what_happened": "w " * 300,
            "price_impact": "p " * 300,
            "sentiment": "bogus",
            "date": "2026-07-10T12:00:00Z",
        }],
        "sentiment_score": 7,
        "sentiment_label": "L" * 100,
        "consumer_take": "c " * 300,
    }
    out = learn_news.analyze_news(
        "MU", None, None, None, NEWS,
        client=_fake_client(noisy, calls), today=TODAY)
    s = out["stories"][0]
    assert len(s["headline"]) <= 90
    assert len(s["what_happened"]) <= 200
    assert len(s["price_impact"]) <= 180
    assert s["sentiment"] == "neutral"          # unknown value coerced
    assert s["date"] == "2026-07-10"            # ISO date only
    assert out["sentiment_score"] == 1.0        # clamped to [-1, 1]
    assert len(out["sentiment_label"]) <= 24
    assert len(out["consumer_take"]) <= 160


def test_analyze_news_cached_per_ticker_day():
    calls = []
    client = _fake_client(PAYLOAD, calls)
    a = learn_news.analyze_news("MU", "Micron", 100.0, 0.2, NEWS,
                                client=client, today=TODAY)
    b = learn_news.analyze_news("MU", "Micron", 100.0, 0.2, NEWS,
                                client=client, today=TODAY)
    assert len(calls) == 1                      # ONE API call for the day
    assert a is b


def test_analyze_news_failure_returns_none_and_negative_caches():
    calls = []
    client = _fake_client(PAYLOAD, calls, fail=True)
    assert learn_news.analyze_news("MU", None, None, None, NEWS,
                                   client=client, today=TODAY) is None
    assert learn_news.analyze_news("MU", None, None, None, NEWS,
                                   client=client, today=TODAY) is None
    assert len(calls) == 1                      # failure cached, no hammering


def test_analyze_news_without_news_makes_no_call():
    calls = []
    out = learn_news.analyze_news("MU", None, None, None, [],
                                  client=_fake_client(PAYLOAD, calls), today=TODAY)
    assert out is None and calls == []


def test_analyze_news_unusable_stories_returns_none():
    calls = []
    empty = {**PAYLOAD, "stories": [{"headline": "", "what_happened": ""}]}
    out = learn_news.analyze_news("MU", None, None, None, NEWS,
                                  client=_fake_client(empty, calls), today=TODAY)
    assert out is None


# --- learn_brief: API budget + price history ----------------------------------

from app import learn_brief
from app.models import PriceHistory

ANALYSIS = {
    "stories": [{
        "headline": "Chipmaker beats on Q2 earnings",
        "what_happened": "Revenue of $8.1B beat estimates.",
        "price_impact": "Beats usually push the stock higher.",
        "sentiment": "positive",
        "date": "2026-07-10",
    }],
    "sentiment_score": 0.6,
    "sentiment_label": "Leaning bullish",
    "consumer_take": "Retail is hyped.",
}


def _pick(ticker="MU"):
    return SimpleNamespace(
        ticker=ticker, price=100.0, momentum_3mo=0.22, screen_score=8.0,
        stance="bullish", confidence=0.7, rank=1, summary="Strong setup.")


@pytest.fixture(autouse=True)
def _fresh_brief_cache():
    learn_brief.clear_brief_cache()
    yield
    learn_brief.clear_brief_cache()


def test_build_brief_fetches_news_once_and_memoizes(monkeypatch):
    calls = {"news": 0}

    def fake_get_news(ticker, limit=8):
        calls["news"] += 1
        assert limit == 8
        return NEWS

    monkeypatch.setattr(learn_brief._NEWS, "get_news", fake_get_news)
    monkeypatch.setattr(learn_brief, "stock_details",
                        lambda t, p: {"name": "Micron", "sector": "Technology"})
    monkeypatch.setattr(learn_brief.learn_news, "analyze_news",
                        lambda *a, **k: dict(ANALYSIS))
    monkeypatch.setattr(learn_brief, "price_history",
                        lambda t, d: {"points": [], "events": []})

    b1 = learn_brief.build_brief(_pick())
    b2 = learn_brief.build_brief(_pick())
    assert calls["news"] == 1               # ONE NewsAPI call, brief memoized
    assert b1 is b2
    assert b1["news_analysis"]["stories"]
    assert b1["news"][0]["title"] == "Chipmaker beats on Q2 earnings"


def test_build_brief_survives_all_providers_down(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("down")

    monkeypatch.setattr(learn_brief._NEWS, "get_news", boom)
    monkeypatch.setattr(learn_brief._MARKET, "get_market_data", boom)
    monkeypatch.setattr(learn_brief._HISTORY, "get_history", boom)
    b = learn_brief.build_brief(_pick("AMD"))
    assert b["news"] == [] and b["news_analysis"] == {} and b["price_history"] == {}
    assert b["reasons"]                     # deterministic reasons still there


def test_price_history_downsamples_and_pins_events(monkeypatch):
    dates = [f"2026-{4 + i // 30:02d}-{i % 30 + 1:02d}" for i in range(90)]
    closes = [100.0 + i for i in range(90)]
    monkeypatch.setattr(
        learn_brief._HISTORY, "get_history",
        lambda t, period="3mo": PriceHistory(ticker=t, dates=dates,
                                             closes=closes))
    h = learn_brief.price_history("MU", ["2026-05-15", ""])
    assert 2 <= len(h["points"]) <= 61
    assert h["points"][-1]["d"] == dates[-1]        # last close always kept
    assert len(h["events"]) == 1                    # empty date skipped
    ev = h["events"][0]
    assert h["points"][ev["i"]]["d"] >= "2026-05-15"
