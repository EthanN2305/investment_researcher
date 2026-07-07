"""Voiceover synthesis for the Learn-tab videos.

Turns the per-scene narration script (see ``learn_brief.build_narration``) into
small audio clips that Remotion embeds via ``<Audio>`` — both in the in-app
``<Player>`` preview and in the server-rendered MP4.

Engine selection is automatic, best-first, and needs no paid API key:

* **edge** — Microsoft Edge's online *neural* voices via the free ``edge-tts``
  package. These sound genuinely human (the same neural voices as Azure) and
  cost nothing; they only need internet access (which the app already uses for
  market data/news). This is the primary engine when available. Output is mp3,
  which Chrome/Remotion plays everywhere.
* **macOS** — the built-in ``say`` command renders speech to AIFF, and
  ``afconvert`` transcodes to AAC/.m4a. Fully offline fallback.
* **Linux** — ``espeak-ng`` + ``ffmpeg`` as a last resort (handy for CI).

If nothing is available (or the machine is offline and only edge was present),
synthesis returns ``available=False`` and the video renders silently — nothing
breaks.

Clips are written under ``frontend/public/voiceover/<key>/`` so Vite serves
them at ``/voiceover/...`` for the preview and Remotion's ``staticFile`` resolves
them for the CLI render.
"""
from __future__ import annotations

import logging
import re
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

_TIMEOUT_S = 60
# Words-per-minute we ask the engine for. Scenes now stretch to fit the audio,
# so we no longer rush to hit a fixed budget — a relaxed, natural pace reads
# far less "robotic". Also used to *estimate* duration when probing fails.
_WPM = 168

# Preferred macOS voice *base names*, best-first — warm, natural US English
# voices. We strongly prefer their "Premium"/"Enhanced" neural variants, which
# sound dramatically more human than the compact defaults. Falls back to the
# system default (None) if none are installed, so a render never breaks.
_PREFERRED_MACOS_VOICES = (
    "Ava", "Zoe", "Evan", "Nathan", "Joelle", "Samantha", "Allison",
    "Susan", "Tom", "Alex",
)
# Quality suffixes, best-first. Premium/Enhanced are the downloadable neural
# voices; "" is the built-in compact voice.
_VOICE_QUALITY = ("(Premium)", "(Enhanced)", "")

# Microsoft Edge neural voices, best-first. These are the same neural voices
# Azure ships (Siri-grade quality) and sound dramatically more human than any
# offline engine. We pick the first that successfully synthesizes a probe.
# Brian leads by preference — a warm, energetic, conversational US male.
_EDGE_VOICES = (
    "en-US-BrianNeural", "en-US-AndrewNeural", "en-US-AvaNeural",
    "en-US-EmmaNeural", "en-US-JennyNeural", "en-US-AriaNeural",
    "en-US-GuyNeural",
)
# A touch of pace so the delivery has energy without sounding rushed.
_EDGE_RATE = "+6%"


def _edge_importable() -> bool:
    try:
        import edge_tts  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


def _macos_ok() -> bool:
    return bool(shutil.which("say") and shutil.which("afconvert"))


def _espeak_ok() -> bool:
    return bool(shutil.which("espeak-ng") and shutil.which("ffmpeg"))


def engine() -> str | None:
    """Return the best available TTS engine id (best-first), or None.

    Note: ``edge`` also requires network at synth time; ``synthesize`` verifies
    that with a quick probe and transparently downgrades if it's offline.
    """
    if _edge_importable():
        return "edge"
    if _macos_ok():
        return "macos"
    if _espeak_ok():
        return "espeak"
    return None


def _offline_engine() -> str | None:
    """The best *offline* engine, used as a fallback when edge can't reach the
    network."""
    if _macos_ok():
        return "macos"
    if _espeak_ok():
        return "espeak"
    return None


def _list_macos_voices() -> list[tuple[str, str]]:
    """Parsed `say -v '?'` → list of (full_name, lang). Full names can contain
    spaces/parentheses, e.g. ("Ava (Premium)", "en_US")."""
    try:
        out = subprocess.run(
            ["say", "-v", "?"], capture_output=True, text=True, timeout=10
        ).stdout
    except Exception:  # noqa: BLE001
        return []
    voices: list[tuple[str, str]] = []
    for ln in out.splitlines():
        # "Ava (Premium)      en_US    # Hello, my name is Ava."
        m = re.match(r"^(.*?)\s{2,}([a-z]{2}[-_][A-Z]{2})", ln)
        if m:
            voices.append((m.group(1).strip(), m.group(2).replace("-", "_")))
    return voices


def _macos_voice() -> str | None:
    """Pick the most natural available English voice, preferring the Premium /
    Enhanced neural variants of our favourite voices. None → system default."""
    voices = _list_macos_voices()
    if not voices:
        return None
    # Index by (base_name, quality_suffix) for exact lookups, US-English first.
    by_name = {name: lang for name, lang in voices}

    def score_lang(name: str) -> int:
        lang = by_name.get(name, "")
        return 0 if lang.startswith("en_US") else (1 if lang.startswith("en") else 2)

    # Try each preferred base name at each quality tier, best-first.
    for quality in _VOICE_QUALITY:
        best = None
        for base in _PREFERRED_MACOS_VOICES:
            full = f"{base} {quality}".strip()
            if full in by_name and by_name[full].startswith("en"):
                if best is None or score_lang(full) < score_lang(best):
                    best = full
                    if score_lang(full) == 0:  # perfect: US-English at this tier
                        break
        if best:
            return best
    # Last resort: any installed English voice.
    for name, lang in voices:
        if lang.startswith("en"):
            return name
    return None


def _spell_out(text: str, spell: list[str] | None) -> str:
    """Spell given tokens as individual letters *for speech only* so tickers
    like "MU" are read "M U" (the letters), never "moo". Case-insensitive,
    whole-word matches; digits inside a ticker are left as-is."""
    if not spell:
        return text
    for tok in spell:
        tok = (tok or "").strip()
        if not tok:
            continue
        spaced = " ".join(list(tok.upper()))  # "MU" -> "M U"
        text = re.sub(rf"\b{re.escape(tok)}\b", spaced, text,
                      flags=re.IGNORECASE)
    return text


def _speechify(text: str, spell: list[str] | None = None) -> str:
    """Expand symbols that TTS engines read awkwardly and spell out tickers.
    Narration is mostly plain, but news headlines can carry $, %, &, etc."""
    text = _spell_out(text, spell)
    repl = {
        "%": " percent", "&": " and ", "×": " times", "@": " at ",
        "—": ", ", "–": ", ", "…": ".",
    }
    for k, v in repl.items():
        text = text.replace(k, v)
    text = re.sub(r"\$\s?(\d[\d,]*(?:\.\d+)?)", r"\1 dollars ", text)  # "$50" -> "50 dollars"
    text = text.replace("$", "")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _estimate_seconds(text: str) -> float:
    words = max(1, len(text.split()))
    return round(words / (_WPM / 60.0), 2)


def _probe_seconds(path: Path) -> float | None:
    """Best-effort audio duration in seconds via afinfo (macOS) or ffprobe."""
    if shutil.which("afinfo"):
        try:
            out = subprocess.run(
                ["afinfo", str(path)], capture_output=True, text=True,
                timeout=15).stdout
            m = re.search(r"estimated duration:\s*([\d.]+)", out)
            if m:
                return round(float(m.group(1)), 2)
        except Exception:  # noqa: BLE001
            pass
    if shutil.which("ffprobe"):
        try:
            out = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries",
                 "format=duration", "-of",
                 "default=noprint_wrappers=1:nokey=1", str(path)],
                capture_output=True, text=True, timeout=15).stdout.strip()
            return round(float(out), 2)
        except Exception:  # noqa: BLE001
            pass
    return None


def _synth_edge(text: str, out_mp3: Path, voice: str, rate: str = _EDGE_RATE) -> bool:
    """Render one clip with an Edge neural voice. Returns True on success.
    Runs the async edge-tts client in a fresh event loop (safe inside the
    render thread)."""
    import asyncio

    import edge_tts

    async def _go() -> None:
        comm = edge_tts.Communicate(text, voice, rate=rate)
        await comm.save(str(out_mp3))

    try:
        asyncio.run(_go())
    except Exception as exc:  # noqa: BLE001 — network/voice errors handled by caller
        logger.info("edge-tts synth failed (%s): %s", voice, exc)
        out_mp3.unlink(missing_ok=True)
        return False
    return out_mp3.exists() and out_mp3.stat().st_size > 0


def _pick_edge_voice() -> str | None:
    """Probe Edge voices in preference order; return the first that actually
    synthesizes (verifies both the package AND network). None if all fail."""
    import tempfile

    probe = Path(tempfile.gettempdir()) / "learn_edge_probe.mp3"
    for voice in _EDGE_VOICES:
        try:
            if _synth_edge("Hello.", probe, voice):
                probe.unlink(missing_ok=True)
                return voice
        except Exception:  # noqa: BLE001
            continue
        finally:
            probe.unlink(missing_ok=True)
    return None


def _synth_macos(text: str, out_m4a: Path, voice: str | None = None) -> bool:
    aiff = out_m4a.with_suffix(".aiff")
    say_cmd = ["say", "-r", str(_WPM)]
    if voice:
        say_cmd += ["-v", voice]
    say_cmd += ["-o", str(aiff), text]
    try:
        r = subprocess.run(
            say_cmd, capture_output=True, text=True, timeout=_TIMEOUT_S)
        if r.returncode != 0 or not aiff.exists():
            logger.warning("say failed: %s", r.stderr[:200])
            return False
        c = subprocess.run(
            ["afconvert", "-f", "m4af", "-d", "aac", str(aiff), str(out_m4a)],
            capture_output=True, text=True, timeout=_TIMEOUT_S)
        return c.returncode == 0 and out_m4a.exists()
    finally:
        aiff.unlink(missing_ok=True)


def _synth_espeak(text: str, out_m4a: Path) -> bool:
    wav = out_m4a.with_suffix(".wav")
    try:
        wpm = str(_WPM)
        r = subprocess.run(
            ["espeak-ng", "-s", wpm, "-w", str(wav), text],
            capture_output=True, text=True, timeout=_TIMEOUT_S)
        if r.returncode != 0 or not wav.exists():
            logger.warning("espeak-ng failed: %s", r.stderr[:200])
            return False
        c = subprocess.run(
            ["ffmpeg", "-y", "-i", str(wav), "-c:a", "aac", "-b:a", "128k",
             str(out_m4a)],
            capture_output=True, text=True, timeout=_TIMEOUT_S)
        return c.returncode == 0 and out_m4a.exists()
    finally:
        wav.unlink(missing_ok=True)


def synthesize(
    narration: dict[str, str],
    out_dir: Path,
    spell_out: list[str] | None = None,
) -> dict:
    """Render each narration line to ``<out_dir>/<scene>.m4a``.

    ``spell_out`` lists tokens (e.g. the ticker) to read as individual letters
    so "MU" is spoken "M U" rather than "moo" — speech only; the on-screen
    captions still show the plain symbol.

    Returns a manifest::

        {
          "available": bool,
          "engine": "edge" | "macos" | "espeak" | None,
          "scenes": { "<id>": {"file": "hook.mp3", "seconds": 2.4}, ... }
        }

    Existing clips are reused (idempotent) regardless of extension, so repeat
    renders are instant.
    """
    eng = engine()
    if eng is None:
        logger.info("learn voice: no TTS engine available — silent video.")
        return {"available": False, "engine": None, "scenes": {}}

    out_dir.mkdir(parents=True, exist_ok=True)

    # Resolve the engine + voice. Edge is preferred but needs network; if the
    # probe fails, transparently fall back to the best offline engine.
    edge_voice: str | None = None
    if eng == "edge":
        edge_voice = _pick_edge_voice()
        if edge_voice is None:
            fallback = _offline_engine()
            logger.info(
                "learn voice: edge-tts unreachable — falling back to %s.",
                fallback or "silent")
            eng = fallback
            if eng is None:
                return {"available": False, "engine": None, "scenes": {}}

    macos_voice = _macos_voice() if eng == "macos" else None
    ext = ".mp3" if eng == "edge" else ".m4a"

    def _synth(spoken: str, out_path: Path) -> bool:
        if eng == "edge":
            return _synth_edge(spoken, out_path, edge_voice)
        if eng == "macos":
            return _synth_macos(spoken, out_path, macos_voice)
        return _synth_espeak(spoken, out_path)

    scenes: dict[str, dict] = {}
    for scene_id, text in narration.items():
        text = (text or "").strip()
        if not text:
            continue
        # Reuse an existing clip only if it was produced by the *current*
        # engine (i.e. its extension matches what this engine emits). This
        # keeps repeats instant while ensuring that upgrading from an offline
        # engine to the neural Edge voice actually regenerates the audio —
        # otherwise a robotic .m4a would be reused forever and the voice would
        # never improve. Stale clips from other engines are overwritten.
        current = out_dir / f"{scene_id}{ext}"
        existing = current if current.exists() else None
        # Drop any leftover clip for this scene from a different engine so we
        # don't strand two files (mp3 + m4a) side by side.
        for e in (".mp3", ".m4a"):
            stale = out_dir / f"{scene_id}{e}"
            if e != ext and stale.exists():
                stale.unlink(missing_ok=True)
        clip_path = existing or current
        if existing is None:
            ok = False
            spoken = _speechify(text, spell_out)
            try:
                ok = _synth(spoken, clip_path)
            except Exception as exc:  # noqa: BLE001 — one bad clip ≠ dead video
                logger.warning("learn voice: %s failed for %r: %s",
                               eng, scene_id, exc)
            if not ok:
                continue
        seconds = _probe_seconds(clip_path) or _estimate_seconds(text)
        scenes[scene_id] = {"file": clip_path.name, "seconds": seconds}

    return {"available": bool(scenes), "engine": eng, "scenes": scenes}
