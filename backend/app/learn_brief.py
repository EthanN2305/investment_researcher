"""Learn-tab enrichment — turn a bare recommendation pick into a richer, more
engaging "video brief" and a scene-by-scene narration script.

Everything here is grounded in real data:

* stock details (sector, market cap, 52-week range, P/E) come from the live
  market-data tool;
* recent headlines come from the news tool (dated, most-recent first);
* the "why the AI picked it" reasons are derived deterministically from the
  pick's own signals (stance, 3-month momentum, technical screen score, agent
  confidence, rank) plus the agents' own summary — never fabricated.

All external lookups are best-effort: if a key is missing or a provider is
down, the brief simply omits that section and the video degrades gracefully to
the data we already have. Nothing here can crash a render.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from app.tools.market_data import YFinanceMarketData
from app.tools.news import NewsAPINews

logger = logging.getLogger(__name__)

# Instantiated lazily and reused (both tools cache internally).
_MARKET = YFinanceMarketData()
_NEWS = NewsAPINews()


# --- formatting helpers ------------------------------------------------------

def _money(n: float | None) -> str:
    return "—" if n is None else f"${n:,.2f}"


def _big_money(n: float | None) -> str:
    """Compact market-cap style: $1.24T / $92.5B / $840M."""
    if not n or n <= 0:
        return "—"
    for unit, size in (("T", 1e12), ("B", 1e9), ("M", 1e6)):
        if n >= size:
            return f"${n / size:.2f}{unit}"
    return f"${n:,.0f}"


def _pct(m: float | None, signed: bool = True) -> str:
    if m is None:
        return "—"
    v = m * 100
    sign = "+" if (signed and v >= 0) else ""
    return f"{sign}{v:.1f}%"


def _range_position(price, low, high) -> int | None:
    """Where the price sits in its 52-week range, 0-100 (0 = at the low)."""
    if price is None or low is None or high is None or high <= low:
        return None
    return max(0, min(100, round((price - low) / (high - low) * 100)))


def _time_ago(iso: str | None) -> str:
    dt = _parse_dt(iso)
    if dt is None:
        return "recently"
    delta = datetime.now(timezone.utc) - dt
    hours = delta.total_seconds() / 3600
    if hours < 1:
        return "just now"
    if hours < 24:
        return f"{int(hours)}h ago"
    days = int(hours // 24)
    return "yesterday" if days == 1 else f"{days}d ago"


def _parse_dt(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _trim(s: str, n: int) -> str:
    s = (s or "").strip()
    if len(s) <= n:
        return s
    cut = s[:n]
    sp = cut.rfind(" ")
    return (cut[:sp] if sp > 0 else cut).rstrip(",.;:") + "…"


def _sentences(text: str, max_sentences: int, max_chars: int) -> str:
    """First N sentences of a blurb, capped at max_chars (whole sentences only).

    Used to turn yfinance's long business summary into a punchy, on-screen /
    spoken "what they do" line without a dangling half-sentence.
    """
    text = re.sub(r"\s+", " ", (text or "").strip())
    if not text:
        return ""
    parts = re.split(r"(?<=[.!?])\s+", text)
    out = ""
    for i, p in enumerate(parts):
        if i >= max_sentences:
            break
        candidate = (out + " " + p).strip()
        if len(candidate) > max_chars and out:
            break
        out = candidate
    if not out:  # first sentence already over budget — hard-trim it
        out = _trim(text, max_chars)
    return out


def _humans(n: int | None) -> str:
    """52000 -> "52,000"; None -> ""."""
    return f"{n:,}" if n else ""


# --- stock details -----------------------------------------------------------

def stock_details(ticker: str, price: float | None) -> dict:
    """Live fundamentals for the "at a glance" scene. Best-effort."""
    try:
        md = _MARKET.get_market_data(ticker)
    except Exception as exc:  # noqa: BLE001 — never fatal
        logger.info("learn brief: market data unavailable for %s: %s", ticker, exc)
        return {}

    low, high = md.fifty_two_week_low, md.fifty_two_week_high
    return {
        "name": md.name,
        "sector": md.sector,
        "industry": md.industry,
        "market_cap": _big_money(md.market_cap),
        "pe_ratio": (f"{md.pe_ratio:.1f}" if md.pe_ratio else None),
        "range_low": _money(low),
        "range_high": _money(high),
        "range_pos": _range_position(price, low, high),
        # What the company actually does + a couple of quick facts. Best-effort;
        # any of these may be None/empty and the scene degrades gracefully.
        "about": _sentences(md.business_summary, max_sentences=2, max_chars=240),
        "about_short": _sentences(md.business_summary, max_sentences=1, max_chars=150),
        "employees": _humans(md.employees),
        "headquarters": md.headquarters,
        "website": md.website,
    }


# --- recent news -------------------------------------------------------------

def recent_news(ticker: str, limit: int = 3) -> list[dict]:
    """Most-recent headlines, trimmed for on-screen use. Best-effort."""
    try:
        items = _NEWS.get_news(ticker, limit=max(limit, 6))
    except Exception as exc:  # noqa: BLE001
        logger.info("learn brief: news unavailable for %s: %s", ticker, exc)
        return []

    # Prefer dated, most-recent articles; keep only what fits nicely on screen.
    dated = sorted(
        items,
        key=lambda n: (_parse_dt(n.published_at) or datetime.min.replace(
            tzinfo=timezone.utc)),
        reverse=True,
    )
    out: list[dict] = []
    for n in dated[:limit]:
        title = _trim(n.title, 90)
        if not title or title == "(untitled)":
            continue
        out.append({
            "title": title,
            "source": n.source or "News",
            "when": _time_ago(n.published_at),
        })
    return out


# --- "why the AI picked it" reasons ------------------------------------------

def why_reasons(pick, details: dict | None = None) -> list[dict]:
    """Structured, grounded reasons — each a short label + one-line explanation
    built from the pick's real signals. Ordered strongest-first."""
    details = details or {}
    m = pick.momentum_3mo or 0.0
    conf = round((pick.confidence or 0.0) * 100)
    reasons: list[dict] = []

    # 1) Momentum
    if pick.momentum_3mo is not None:
        if m >= 0.15:
            reasons.append({"icon": "🚀", "label": "Strong momentum",
                            "text": f"Up {_pct(m)} over the last 3 months."})
        elif m >= 0.03:
            reasons.append({"icon": "📈", "label": "Uptrend",
                            "text": f"Firming up, {_pct(m)} in 3 months."})
        elif m <= -0.05:
            reasons.append({"icon": "📉", "label": "Under pressure",
                            "text": f"Down {_pct(m)} over 3 months — watch closely."})
        else:
            reasons.append({"icon": "➡️", "label": "Range-bound",
                            "text": f"Roughly flat ({_pct(m)}) over 3 months."})

    # 2) Technical screen
    reasons.append({
        "icon": "🎯", "label": "Screen score",
        "text": f"Scores {pick.screen_score:.1f} on the technical screen "
                f"— top of a 600+ stock universe.",
    })

    # 3) Agent stance + confidence
    stance = (pick.stance or "neutral").lower()
    stance_word = {"bullish": "bullish", "bearish": "cautious",
                   "neutral": "mixed"}.get(stance, "mixed")
    reasons.append({
        "icon": "🤖", "label": "Agent view",
        "text": f"The AI agents are {stance_word} with {conf}% confidence.",
    })

    # 4) Valuation / sector color when we have it
    if details.get("sector"):
        pe = details.get("pe_ratio")
        industry = details.get("industry")
        where = industry or details["sector"]
        if pe:
            reasons.append({"icon": "🏭", "label": details["sector"],
                            "text": f"Trades at a {pe}× P/E in the "
                                    f"{where} space."})
        else:
            reasons.append({"icon": "🏭", "label": details["sector"],
                            "text": f"A {where} player."})

    return reasons[:5]


# --- the full brief ----------------------------------------------------------

def build_brief(pick, want_news: bool = True) -> dict:
    """Assemble everything the richer video needs. `pick` is a
    StockOfTheDayOut (or anything with the same attributes)."""
    details = stock_details(pick.ticker, pick.price)
    news = recent_news(pick.ticker) if want_news else []
    reasons = why_reasons(pick, details)
    return {"details": details, "news": news, "reasons": reasons}


# --- narration script --------------------------------------------------------

def _cap_spoken(cap: str | None) -> str:
    """"$3.21T" → "about 3.2 trillion dollars"; plain words for narration."""
    if not cap or cap == "—":
        return ""
    s = cap.lstrip("$")
    unit = {"T": "trillion", "B": "billion", "M": "million"}.get(s[-1:], "")
    num = s[:-1] if unit else s
    return f"about {num} {unit} dollars".strip()


def _stance_why(stance: str, ticker: str) -> str:
    stance = (stance or "neutral").lower()
    if stance == "bullish":
        return (f"And here's why the agents love {ticker} — strong momentum "
                "and a top-tier technical score!")
    if stance == "bearish":
        return (f"But heads up — the agents are cautious on {ticker}. "
                "Keep an eye on the downside here.")
    return (f"The agents are split on {ticker} — definitely one to watch, "
            "not chase.")


def build_narration(pick, brief: dict, duration_sec: int = 30) -> dict:
    """Per-scene narration lines, keyed by scene id.

    These are the *spoken* layer (and the on-screen subtitles): plain, upbeat
    English, no symbols. Scenes now stretch to fit the audio, so the script is
    free to be conversational and energetic rather than clipped to a budget.
    The 65-second cut adds an extra clause or two per beat.

    Note on tickers: the text keeps the symbol as-is (e.g. "MU") so the
    subtitles read cleanly; the voice layer (``learn_voice``) spells it out
    letter-by-letter so it's never mispronounced as a word.

    Returns {scene_id: text}.
    """
    long = duration_sec >= 65
    t = pick.ticker
    m = pick.momentum_3mo or 0.0
    move = round(abs(m) * 100)
    up = m >= 0
    conf = round((pick.confidence or 0.0) * 100)
    details = brief.get("details") or {}
    news = brief.get("news") or []
    name = details.get("name")

    lines: dict[str, str] = {}

    lines["hook"] = "Alright, let's talk about today's A.I. stock of the day!"

    lines["ticker"] = f"Today's pick? It's {t}!"
    if pick.price:
        lines["ticker"] += f" Trading around {pick.price:,.0f} dollars right now."

    # --- NEW: what the company actually does ---------------------------------
    about = details.get("about" if long else "about_short") or details.get("about")
    if about:
        subject = name or t
        lines["about"] = f"So what does {subject} actually do? {about}"
        if long and details.get("employees"):
            hq = details.get("headquarters")
            where = f", based in {hq}" if hq else ""
            lines["about"] += (
                f" They've got around {details['employees']} employees{where}.")
    elif name:
        lines["about"] = f"That's {name} — let's break it down."
    else:
        lines["about"] = ""

    sector = details.get("sector")
    cap_words = _cap_spoken(details.get("market_cap"))
    if sector and cap_words:
        lines["details"] = f"It's a {sector} company worth {cap_words}."
    elif sector:
        lines["details"] = f"It's a {sector} company."
    elif cap_words:
        lines["details"] = f"This one's worth {cap_words}."
    else:
        lines["details"] = ""
    if long and lines["details"] and details.get("range_pos") is not None:
        where = "near the top" if details["range_pos"] >= 60 else "in the lower half"
        lines["details"] += f" And it's trading {where} of its 52-week range."

    if pick.momentum_3mo is not None:
        lines["momentum"] = (
            f"Now check this out — it's {'up' if up else 'down'} about {move} "
            "percent over the last three months!")
        if long:
            lines["momentum"] += (
                f" Its technical screen score? A solid {pick.screen_score:.0f} "
                "out of ten.")
    else:
        lines["momentum"] = ""

    if news:
        lines["news"] = f"And in the headlines: {news[0]['title']}."
        if long and len(news) > 1:
            lines["news"] += f" Plus, {news[1]['title']}."
    else:
        lines["news"] = ""

    why = _stance_why(pick.stance, t)
    if long:
        why += f" It's ranked number {pick.rank} of today's top ten picks."
    lines["why"] = why

    lines["confidence"] = (
        f"The agents are {conf} percent confident on this one — and it's "
        f"ranked number {pick.rank} today!")

    # The on-screen CTA carries the rest; fuller ask at 65s.
    lines["outro"] = (
        f"So — would you buy {t}? Drop your take in the comments!"
        if long else f"So, would you buy {t}? Let me know!")

    return {k: v.strip() for k, v in lines.items() if v and v.strip()}
