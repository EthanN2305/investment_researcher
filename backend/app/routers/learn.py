"""Learn tab — a "stock of the day" video (30s or 1m05s) sourced from the
latest recommendations sweep.

GET  /learn/stock-of-the-day       → today's pick (date-seeded from the latest
                                     recommendations run; same stock all day)
GET  /learn/picks                  → the full latest top-10, so the user can
                                     pick any ranked stock for their video
POST /learn/render                 → render the pick to a TikTok-ready MP4
                                     (1080x1920, 30s or 65s) via Remotion;
                                     returns job_id
GET  /learn/render/{job_id}        → render progress ("bundling"/"rendering")
GET  /learn/render/{job_id}/file   → download the finished MP4

Rendering shells out to the Remotion CLI in the frontend project
(`npx remotion render remotion/index.jsx StockOfTheDay …`), so Node must be
installed where the backend runs. Finished videos are cached per
(run, ticker, day) under backend/renders/ — a second download is instant.
"""
from __future__ import annotations

import json
import random
import subprocess
import tempfile
import threading
import uuid
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.db import get_db
from app.db_models import RecommendationItem, User
from app import learn_voice
from app.learn_brief import build_brief, build_narration

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_FRONTEND_DIR = _PROJECT_ROOT / "frontend"
_RENDER_DIR = _PROJECT_ROOT / "backend" / "renders"
# Voiceover clips live in the frontend's public/ so Vite serves them to the
# in-app <Player> preview and Remotion's staticFile() resolves them for renders.
_VOICE_DIR = _FRONTEND_DIR / "public" / "voiceover"
_RENDER_TIMEOUT_S = 15 * 60
_ALLOWED_DURATIONS = (30, 65)  # seconds: 30s and 1m05s
# Bump when the narration script, voice, or composition changes so stale cached
# voiceover clips / MP4s are bypassed instead of reused.
_CACHE_VERSION = "v6"  # v6: quiz hook, real chart, news deep-dive + sentiment


class StockOfTheDayOut(BaseModel):
    ticker: str
    rank: int
    price: float | None = None
    screen_score: float
    momentum_3mo: float | None = None
    stance: str
    confidence: float
    summary: str
    date: str          # the day this pick is valid for (YYYY-MM-DD)
    date_label: str    # human-friendly, baked into the video
    run_id: str        # recommendations sweep it came from
    title: str         # ready-to-post video title (YouTube/TikTok caption)
    description: str   # ready-to-post video description w/ key points + tags
    # Enriched "video brief" fields (populated for single-pick endpoints, left
    # empty for the fast top-10 list). Grounded in live data; see learn_brief.
    details: dict = {}      # sector, market cap, 52-wk range, P/E …
    news: list = []         # recent headlines: [{title, source, when}]
    reasons: list = []      # why the AI picked it: [{icon, label, text}]
    captions: dict = {}     # per-scene narration text (subtitles)
    news_analysis: dict = {}  # LLM news deep-dive: stories + sentiment gauge
    price_history: dict = {}  # real 3-mo closes + news-event pins for the chart


class VoiceoverOut(BaseModel):
    available: bool
    engine: str | None = None
    dir: str | None = None      # public-relative dir, e.g. "voiceover/<key>"
    scenes: dict = {}           # {scene_id: {file, seconds}}
    captions: dict = {}         # length-specific narration text (subtitles)


_STANCE_WORD = {
    "bullish": "Bullish",
    "bearish": "Bearish",
    "neutral": "Neutral",
}


def _money(n: float | None) -> str:
    return "—" if n is None else f"${n:,.2f}"


def _momentum_str(m: float | None) -> str:
    if m is None:
        return "—"
    pct = m * 100
    return f"{'+' if pct >= 0 else ''}{pct:.1f}%"


def _video_title(pick: RecommendationItem | StockOfTheDayOut) -> str:
    """A punchy, click-worthy title derived from the pick's real signals.
    Seeded on (ticker, date) so it's stable for a given day's video."""
    t = pick.ticker
    m = pick.momentum_3mo or 0.0
    seed = getattr(pick, "date", "") or date.today().isoformat()
    rng = random.Random(f"title:{t}:{seed}")

    if pick.stance == "bullish":
        if m >= 0.15:
            options = [
                f"${t} Just Broke Out — Is It Still a Buy?",
                f"${t} Is on a Tear — Too Late to Get In?",
                f"Why the AI Agents Are Bullish on ${t}",
            ]
        else:
            options = [
                f"Why the AI Agents Like ${t} Right Now",
                f"${t}: The AI's Bullish Pick of the Day",
                f"Is ${t} Quietly Setting Up for a Run?",
            ]
    elif pick.stance == "bearish":
        options = [
            f"Is ${t} Flashing a Warning? 🚩",
            f"Why the AI Agents Are Cautious on ${t}",
            f"${t}: Time to Take Profits?",
        ]
    else:
        options = [
            f"${t}: Buy, Hold, or Wait?",
            f"The AI Is Split on ${t} — Here's Why",
            f"${t}: Today's Wildcard Pick",
        ]
    return rng.choice(options)


def _video_description(pick: RecommendationItem | StockOfTheDayOut) -> str:
    """A ready-to-paste video description: hook, key points, disclaimer, tags —
    built entirely from the pick's real data so nothing is fabricated."""
    t = pick.ticker
    stance = (pick.stance or "neutral").lower()
    stance_word = _STANCE_WORD.get(stance, "Neutral")
    m = pick.momentum_3mo or 0.0
    conf = round((pick.confidence or 0.0) * 100)

    if stance == "bullish":
        hook = (
            f"Today's pick is ${t}, and the AI agents are leaning bullish. "
            f"It's been {'surging' if m >= 0.15 else 'firming up'} over the "
            "past three months and screens well on technicals."
        )
    elif stance == "bearish":
        hook = (
            f"Today's pick is ${t}, and the AI agents are flashing caution. "
            "The setup has some red flags worth watching before you touch it."
        )
    else:
        hook = (
            f"Today's pick is ${t} — a genuine coin-flip. The AI agents see a "
            "mixed picture, so it's one to watch rather than chase."
        )

    key_points = [
        f"• Stance: {stance_word}",
        f"• Price: {_money(pick.price)}",
        f"• 3-month momentum: {_momentum_str(m)}",
        f"• Technical screen score: {pick.screen_score:.1f}",
        f"• Agent confidence: {conf}%",
        f"• Ranked #{pick.rank} of today's top 10 AI picks",
    ]

    # A trimmed line from the agents' own summary adds color when present.
    summary = (pick.summary or "").strip()
    if summary:
        first = summary.split(". ")[0].strip().rstrip(".")
        if first:
            key_points.append(f"• Agents' take: {first[:120]}")

    tags = f"#StockOfTheDay #{t} #StockMarket #Investing #Stocks #AI #Technicals"

    return (
        f"📈 Stock of the Day: ${t}\n\n"
        f"{hook}\n\n"
        "🔑 Key points:\n"
        + "\n".join(key_points)
        + "\n\n⚠️ Not financial advice — just a quick, AI-generated technical "
        "snapshot for education/entertainment purposes. Always do your own "
        "research before trading.\n\n"
        + tags
    )


@dataclass
class RenderJob:
    id: str
    ticker: str
    duration_sec: int = 30
    phase: str = "starting"  # starting | browser | bundling | rendering | done | error
    status: str = "running"  # running | done | error
    output: Path | None = None
    error: str | None = None

    def as_dict(self) -> dict:
        return {
            "job_id": self.id,
            "ticker": self.ticker,
            "duration_sec": self.duration_sec,
            "status": self.status,
            "phase": self.phase,
            "error": self.error,
        }


_JOBS: dict[str, RenderJob] = {}
_RENDER_LOCK = threading.Lock()

router = APIRouter(tags=["learn"])


def _latest_items(db: Session) -> list[RecommendationItem]:
    newest = db.scalar(
        select(RecommendationItem)
        .order_by(
            RecommendationItem.created_at.desc(), RecommendationItem.id.desc()
        )
        .limit(1)
    )
    if newest is None:
        raise HTTPException(
            404,
            "No recommendations yet — generate picks on the Recommendations "
            "tab first.",
        )
    return db.scalars(
        select(RecommendationItem)
        .where(RecommendationItem.run_id == newest.run_id)
        .order_by(RecommendationItem.rank.asc())
    ).all()


def _to_out(
    pick: RecommendationItem, today: date, *, enrich: bool = False
) -> StockOfTheDayOut:
    out = StockOfTheDayOut(
        ticker=pick.ticker,
        rank=pick.rank,
        price=pick.price,
        screen_score=pick.screen_score,
        momentum_3mo=pick.momentum_3mo,
        stance=pick.stance,
        confidence=pick.confidence,
        summary=pick.summary,
        date=today.isoformat(),
        date_label=today.strftime("%B %-d, %Y"),
        run_id=pick.run_id,
        title="",
        description="",
    )
    out.title = _video_title(out)
    out.description = _video_description(out)
    if enrich:
        # Live details + recent news + structured reasons + subtitle captions.
        # Best-effort: build_brief never raises. Captions default to the 30s
        # narration; the render regenerates them per chosen length.
        brief = build_brief(out)
        out.details = brief["details"]
        out.news = brief["news"]
        out.reasons = brief["reasons"]
        out.captions = build_narration(out, brief, 30)
        out.news_analysis = brief["news_analysis"]
        out.price_history = brief["price_history"]
    return out


def _pick_of_the_day(db: Session, *, enrich: bool = False) -> StockOfTheDayOut:
    """Deterministic daily pick: seed the RNG with (day, run_id) so everyone
    sees the same stock until midnight or a new sweep lands."""
    items = _latest_items(db)
    today = date.today()
    pick = random.Random(f"{today.isoformat()}:{items[0].run_id}").choice(items)
    return _to_out(pick, today, enrich=enrich)


def _pick_ticker(
    db: Session, ticker: str, *, enrich: bool = False
) -> StockOfTheDayOut:
    """A specific stock from the latest top-10 (for shuffled videos)."""
    items = _latest_items(db)
    for item in items:
        if item.ticker == ticker:
            return _to_out(item, date.today(), enrich=enrich)
    raise HTTPException(404, f"{ticker} is not in the latest top 10.")


def _cached_path(pick: StockOfTheDayOut, duration_sec: int) -> Path:
    return (
        _RENDER_DIR
        / f"{pick.run_id}_{pick.date}_{pick.ticker}_{duration_sec}s_{_CACHE_VERSION}.mp4"
    )


def _voice_key(pick: StockOfTheDayOut, duration_sec: int) -> str:
    return f"{pick.run_id}_{pick.date}_{pick.ticker}_{duration_sec}s_{_CACHE_VERSION}"


def _voice_rel(pick: StockOfTheDayOut, duration_sec: int) -> str:
    """Public-relative dir the composition passes to staticFile()."""
    return f"voiceover/{_voice_key(pick, duration_sec)}"


def _make_voiceover(pick: StockOfTheDayOut, duration_sec: int) -> dict:
    """Build the narration and synthesize per-scene clips (idempotent).
    Returns a manifest dict shaped like VoiceoverOut; never raises."""
    try:
        brief = {
            "details": pick.details, "news": pick.news, "reasons": pick.reasons,
            "news_analysis": pick.news_analysis,
        }
        narration = build_narration(pick, brief, duration_sec)
        out_dir = _VOICE_DIR / _voice_key(pick, duration_sec)
        # Spell the ticker out as letters for speech (e.g. "MU" -> "M U").
        manifest = learn_voice.synthesize(
            narration, out_dir, spell_out=[pick.ticker])
        manifest["dir"] = _voice_rel(pick, duration_sec) if manifest[
            "available"] else None
        # Return the length-specific narration so preview subtitles match audio.
        manifest["captions"] = narration
        return manifest
    except Exception:  # noqa: BLE001 — voiceover is a nicety, never fatal
        return {"available": False, "engine": None, "dir": None,
                "scenes": {}, "captions": {}}


def _error_summary(output: str) -> str:
    """Pull the meaningful error line(s) out of CLI output.

    Remotion prints the real message before a long stack trace; keeping the
    *tail* of stderr (the old behaviour) surfaced only useless "at …" frames.
    """
    lines = [
        ln.strip()
        for ln in output.splitlines()
        if ln.strip()
        and not ln.strip().startswith(("at ", "npm notice", "npm warn"))
    ]
    for i, ln in enumerate(lines):
        if "error" in ln.lower():
            return " ".join(lines[i : i + 3])[:400]
    return " ".join(lines[-3:])[:400] or "Remotion render failed."


def _run_render(
    job: RenderJob,
    pick: StockOfTheDayOut,
    out_path: Path,
    duration_sec: int,
) -> None:
    # Enrich with live details/news/reasons, build the length-specific captions,
    # and synthesize the voiceover — all best-effort so a render never fails on
    # a missing news key or TTS engine.
    brief = build_brief(pick)
    pick.details = brief["details"]
    pick.news = brief["news"]
    pick.reasons = brief["reasons"]
    pick.news_analysis = brief["news_analysis"]
    pick.price_history = brief["price_history"]
    captions = build_narration(pick, brief, duration_sec)
    voice = _make_voiceover(pick, duration_sec)

    props = {
        "ticker": pick.ticker,
        "price": pick.price,
        "stance": pick.stance,
        "confidence": pick.confidence,
        "momentum_3mo": pick.momentum_3mo,
        "screen_score": pick.screen_score,
        "rank": pick.rank,
        "summary": pick.summary,
        "date_label": pick.date_label,
        "duration_sec": duration_sec,
        "details": pick.details,
        "news": pick.news,
        "reasons": pick.reasons,
        "news_analysis": pick.news_analysis,
        "price_history": pick.price_history,
        "captions": captions,
        "voice": voice,
    }
    try:
        _RENDER_DIR.mkdir(parents=True, exist_ok=True)
        log_path = _RENDER_DIR / f"render_{job.id}.log"
        with tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False
        ) as f:
            json.dump(props, f)
            props_file = f.name

        # Remotion renders in Chrome Headless Shell. On a fresh machine it
        # isn't installed yet (no frontend/node_modules/.remotion), and the
        # implicit ~100 MB download inside `remotion render` is exactly what
        # blew up before. Ensure it explicitly so failures are legible.
        job.phase = "browser"
        browser = subprocess.run(
            ["npx", "remotion", "browser", "ensure"],
            cwd=_FRONTEND_DIR,
            capture_output=True,
            text=True,
            timeout=_RENDER_TIMEOUT_S,
        )
        log_path.write_text(
            f"$ npx remotion browser ensure\n{browser.stdout}\n{browser.stderr}\n"
        )
        if browser.returncode != 0:
            raise RuntimeError(
                "Could not set up Chrome Headless Shell (a one-time ~100 MB "
                "download Remotion needs to render): "
                + _error_summary(browser.stderr or browser.stdout or "")
            )

        job.phase = "bundling"
        tmp_out = out_path.with_suffix(".tmp.mp4")
        cmd = [
            "npx", "remotion", "render",
            "remotion/index.jsx", "StockOfTheDay", str(tmp_out),
            f"--props={props_file}",
            "--codec=h264",
        ]
        job.phase = "rendering"
        proc = subprocess.run(
            cmd,
            cwd=_FRONTEND_DIR,
            capture_output=True,
            text=True,
            timeout=_RENDER_TIMEOUT_S,
        )
        with log_path.open("a") as log:
            log.write(f"\n$ {' '.join(cmd)}\n{proc.stdout}\n{proc.stderr}\n")
        if proc.returncode != 0 or not tmp_out.exists():
            raise RuntimeError(
                _error_summary(proc.stderr or proc.stdout or "")
            )
        tmp_out.replace(out_path)
        job.output = out_path
        job.phase = "done"
        job.status = "done"
    except Exception as exc:  # noqa: BLE001 — surface, don't crash the thread
        job.phase = "error"
        job.status = "error"
        job.error = str(exc)[:300]


class RenderRequest(BaseModel):
    ticker: str | None = None  # None → today's deterministic pick
    duration_sec: int = 30     # 30 or 65 (1m05s)


@router.get("/learn/stock-of-the-day", response_model=StockOfTheDayOut)
def stock_of_the_day(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    return _pick_of_the_day(db, enrich=True)


@router.get("/learn/picks", response_model=list[StockOfTheDayOut])
def learn_picks(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """The full latest top-10 (rank order) so the user can pick any stock —
    e.g. "#2 of the day" — for their video. Kept lightweight (no live lookups)
    so the list loads instantly; the brief is enriched when a stock is picked."""
    today = date.today()
    return [_to_out(item, today) for item in _latest_items(db)]


@router.get("/learn/shuffle", response_model=StockOfTheDayOut)
def shuffle_pick(
    exclude: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """A random different stock from the latest top-10 (true random, not
    date-seeded) — powers the "another stock" button on the Learn tab."""
    items = _latest_items(db)
    pool = [i for i in items if i.ticker != (exclude or "").upper()] or items
    return _to_out(random.choice(pool), date.today(), enrich=True)


class VoiceoverRequest(BaseModel):
    ticker: str | None = None  # None → today's deterministic pick
    duration_sec: int = 30


@router.post("/learn/voiceover", response_model=VoiceoverOut)
def make_voiceover(
    req: VoiceoverRequest | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Generate (or reuse) the narration audio for a pick so the in-app preview
    can play it. Returns a manifest of per-scene clips; `available` is false
    when no TTS engine is installed (the video just plays silently)."""
    ticker = (req.ticker if req else None) or None
    duration_sec = req.duration_sec if req else 30
    if duration_sec not in _ALLOWED_DURATIONS:
        raise HTTPException(
            422, f"duration_sec must be one of {list(_ALLOWED_DURATIONS)}."
        )
    pick = (
        _pick_ticker(db, ticker.strip().upper(), enrich=True)
        if ticker
        else _pick_of_the_day(db, enrich=True)
    )
    return _make_voiceover(pick, duration_sec)


@router.post("/learn/render", status_code=202)
def start_render(
    req: RenderRequest | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    ticker = (req.ticker if req else None) or None
    duration_sec = req.duration_sec if req else 30
    if duration_sec not in _ALLOWED_DURATIONS:
        raise HTTPException(
            422,
            f"duration_sec must be one of {list(_ALLOWED_DURATIONS)} "
            "(30s or 1m05s).",
        )
    pick = (
        _pick_ticker(db, ticker.strip().upper())
        if ticker
        else _pick_of_the_day(db)
    )
    out_path = _cached_path(pick, duration_sec)

    with _RENDER_LOCK:
        # Already rendered today → instant "done" job pointing at the cache.
        if out_path.exists():
            job = RenderJob(
                id=uuid.uuid4().hex[:12], ticker=pick.ticker,
                duration_sec=duration_sec,
                phase="done", status="done", output=out_path,
            )
            _JOBS[job.id] = job
            return job.as_dict()
        if any(j.status == "running" for j in _JOBS.values()):
            raise HTTPException(409, "A video render is already in progress.")
        job = RenderJob(
            id=uuid.uuid4().hex[:12], ticker=pick.ticker,
            duration_sec=duration_sec,
        )
        _JOBS[job.id] = job

    threading.Thread(
        target=_run_render, args=(job, pick, out_path, duration_sec),
        name=f"learn-render-{job.id}", daemon=True,
    ).start()
    return job.as_dict()


@router.get("/learn/render/{job_id}")
def render_status(
    job_id: str, user: User = Depends(get_current_user)
) -> dict:
    job = _JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, "Unknown render job.")
    return job.as_dict()


@router.get("/learn/render/{job_id}/file")
def render_file(job_id: str, user: User = Depends(get_current_user)):
    job = _JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, "Unknown render job.")
    if job.status != "done" or job.output is None or not job.output.exists():
        raise HTTPException(409, "Video is not ready yet.")
    label = "1m05s" if job.duration_sec == 65 else f"{job.duration_sec}s"
    return FileResponse(
        job.output,
        media_type="video/mp4",
        filename=f"{job.ticker}-stock-of-the-day-{label}.mp4",
    )
