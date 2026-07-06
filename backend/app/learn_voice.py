"""Voiceover synthesis for the Learn-tab videos.

Turns the per-scene narration script (see ``learn_brief.build_narration``) into
small audio clips that Remotion embeds via ``<Audio>`` — both in the in-app
``<Player>`` preview and in the server-rendered MP4.

Engine selection is automatic and fully offline (no API keys):

* **macOS** — the built-in ``say`` command renders speech to AIFF, and
  ``afconvert`` transcodes to AAC/.m4a (Chrome, and therefore Remotion, plays
  m4a everywhere). This is the primary path since the app runs on macOS.
* **Linux** — ``espeak-ng`` + ``ffmpeg`` as a fallback (handy for CI/servers).

If no engine is available, synthesis returns ``available=False`` and the video
simply renders without a voiceover track — nothing breaks.

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

# Preferred macOS voices, best-first. These are warm, clear US English voices
# that sound noticeably more human than the system default; we fall back to the
# default (None) if none are installed, so this never breaks a render.
_PREFERRED_MACOS_VOICES = ("Samantha", "Ava", "Allison", "Zoe", "Tom", "Alex")


def engine() -> str | None:
    """Return the available TTS engine id, or None."""
    if shutil.which("say") and shutil.which("afconvert"):
        return "macos"
    if shutil.which("espeak-ng") and shutil.which("ffmpeg"):
        return "espeak"
    return None


def _macos_voice() -> str | None:
    """Pick the best available preferred macOS voice, or None for the default."""
    try:
        out = subprocess.run(
            ["say", "-v", "?"], capture_output=True, text=True, timeout=10
        ).stdout
    except Exception:  # noqa: BLE001
        return None
    installed = {ln.split()[0] for ln in out.splitlines() if ln.strip()}
    for v in _PREFERRED_MACOS_VOICES:
        if v in installed:
            return v
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
          "engine": "macos" | "espeak" | None,
          "scenes": { "<id>": {"file": "hook.m4a", "seconds": 2.4}, ... }
        }

    Existing clips are reused (idempotent), so repeat renders are instant.
    """
    eng = engine()
    if eng is None:
        logger.info("learn voice: no TTS engine available — silent video.")
        return {"available": False, "engine": None, "scenes": {}}

    out_dir.mkdir(parents=True, exist_ok=True)
    voice = _macos_voice() if eng == "macos" else None

    scenes: dict[str, dict] = {}
    for scene_id, text in narration.items():
        text = (text or "").strip()
        if not text:
            continue
        out_m4a = out_dir / f"{scene_id}.m4a"
        if not out_m4a.exists():
            ok = False
            spoken = _speechify(text, spell_out)
            try:
                if eng == "macos":
                    ok = _synth_macos(spoken, out_m4a, voice)
                else:
                    ok = _synth_espeak(spoken, out_m4a)
            except Exception as exc:  # noqa: BLE001 — one bad clip ≠ dead video
                logger.warning("learn voice: %s failed for %r: %s",
                               eng, scene_id, exc)
            if not ok:
                continue
        seconds = _probe_seconds(out_m4a) or _estimate_seconds(text)
        scenes[scene_id] = {"file": out_m4a.name, "seconds": seconds}

    return {"available": bool(scenes), "engine": eng, "scenes": scenes}
