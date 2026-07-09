"""In-process progress event bus (asyncio-native consumer side).

Graph nodes can't hold non-serializable objects (checkpointing deep-copies
state), so nodes publish events here keyed by `run_id`. Events go into an
append-only history per run, so any number of SSE subscribers can replay from
any index — late subscribers and reconnects see every event exactly once.

Producers are worker threads (the run pool); the consumer is the FastAPI
event loop. So `emit()` is thread-safe and bridges thread → loop with
`loop.call_soon_threadsafe(...)`, while `get()` is an async coroutine that
awaits new events without pinning a threadpool thread (Phase 1.1).

History is bounded by `unregister()` — the run manager evicts finished runs on
a TTL sweep (Phase 1.3), so nothing lives for the whole process lifetime.
"""
from __future__ import annotations

import asyncio
import threading
import time


class _Channel:
    """Per-run append-only history plus a loop-bound wake signal.

    `history` is appended by worker threads and read by the loop, so all access
    goes through the module-level `_LOCK`. `wake` is an `asyncio.Event` created
    lazily on the loop side; producers set it via `loop.call_soon_threadsafe`.
    """

    __slots__ = ("history", "loop", "wake", "closed")

    def __init__(self) -> None:
        self.history: list[dict] = []
        self.loop: asyncio.AbstractEventLoop | None = None
        self.wake: asyncio.Event | None = None
        self.closed = False

    def _wake_all(self) -> None:
        """Runs on the event loop: signal all current waiters, then reset."""
        ev, self.wake = self.wake, None
        if ev is not None:
            ev.set()

    def _notify(self) -> None:
        """Schedule `_wake_all` on the bound loop from a producer thread.

        The loop may already be closed (e.g. eviction firing during shutdown);
        in that case there is no subscriber left to wake, so swallow it.
        """
        loop = self.loop
        if loop is None:
            return
        try:
            loop.call_soon_threadsafe(self._wake_all)
        except RuntimeError:
            pass  # loop closed / not running — nothing to wake


_LOCK = threading.Lock()
_CHANNELS: dict[str, _Channel] = {}


def register(run_id: str) -> None:
    with _LOCK:
        _CHANNELS[run_id] = _Channel()


def unregister(run_id: str) -> None:
    """Drop a run's history and wake any lingering subscribers so they stop."""
    with _LOCK:
        chan = _CHANNELS.pop(run_id, None)
        if chan is None:
            return
        chan.closed = True
    chan._notify()


def emit(run_id: str, event: dict) -> None:
    """Append an event (called from graph worker threads) and wake the loop."""
    with _LOCK:
        chan = _CHANNELS.get(run_id)
        if chan is None:
            return
        chan.history.append({**event, "ts": time.time()})
    # Bridge thread → event loop: the SSE consumer awaits `chan.wake`.
    chan._notify()


async def get(run_id: str, index: int, timeout: float = 15.0) -> dict | None:
    """Return the event at `index`, awaiting up to `timeout` for it to arrive.

    Async so the SSE path never blocks an AnyIO threadpool thread. Returns None
    on timeout (caller sends a keepalive) or when the run is unknown/evicted.
    """
    with _LOCK:
        chan = _CHANNELS.get(run_id)
        if chan is None:
            return None
        # First subscriber binds the channel to the running loop for emit().
        chan.loop = asyncio.get_running_loop()
        if len(chan.history) > index:
            return chan.history[index]
        if chan.closed:
            return None
        if chan.wake is None:
            chan.wake = asyncio.Event()
        wake = chan.wake

    try:
        await asyncio.wait_for(wake.wait(), timeout)
    except (asyncio.TimeoutError, TimeoutError):
        return None

    with _LOCK:
        chan = _CHANNELS.get(run_id)
        if chan is None:
            return None
        return chan.history[index] if len(chan.history) > index else None
