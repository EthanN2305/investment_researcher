"""In-process progress event bus.

Graph nodes can't hold non-serializable objects (checkpointing deep-copies
state), so nodes publish events here keyed by `run_id`. Events go into an
append-only history per run, so any number of SSE subscribers can replay from
any index — late subscribers and reconnects see every event exactly once.

History lives for the process lifetime (runs are in-memory-only in Phase 2).
"""
from __future__ import annotations

import threading
import time

_LOCK = threading.Lock()
_HISTORY: dict[str, list[dict]] = {}
_CONDS: dict[str, threading.Condition] = {}


def register(run_id: str) -> None:
    with _LOCK:
        _HISTORY[run_id] = []
        _CONDS[run_id] = threading.Condition()


def emit(run_id: str, event: dict) -> None:
    with _LOCK:
        hist = _HISTORY.get(run_id)
        cond = _CONDS.get(run_id)
    if hist is None or cond is None:
        return
    with cond:
        hist.append({**event, "ts": time.time()})
        cond.notify_all()


def get(run_id: str, index: int, timeout: float = 15.0) -> dict | None:
    """Return the event at `index`, waiting up to `timeout` for it to arrive.

    Returns None on timeout (caller sends an SSE keepalive) or unknown run.
    """
    with _LOCK:
        hist = _HISTORY.get(run_id)
        cond = _CONDS.get(run_id)
    if hist is None or cond is None:
        return None
    with cond:
        if len(hist) > index:
            return hist[index]
        cond.wait(timeout)
        return hist[index] if len(hist) > index else None
