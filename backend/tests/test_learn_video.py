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
