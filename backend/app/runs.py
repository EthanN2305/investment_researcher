"""Run lifecycle manager.

Executes the LangGraph on a bounded worker pool (one task per run), bridges
node progress events to an async-consumable event bus, and handles the
planner's interrupt/resume cycle:

  start()  → invoke(graph)      → done | waiting_input (interrupt surfaced)
  answer() → invoke(Command(resume=...)) picks up from the checkpoint

Phase 1 hardening:
- Runs execute on a bounded `ThreadPoolExecutor` (config: RUN_MAX_WORKERS) with
  a bounded backlog (RUN_MAX_QUEUED); past that `start()` raises `RunPoolFull`
  so the API can return 429 instead of fanning out unbounded LLM spend (1.2).
- The SSE generator is `async` and awaits the event bus, so it never pins an
  AnyIO threadpool thread (1.1).
- Finished runs (and their event history) are evicted on a TTL sweep so memory
  stays flat over a long soak (1.3).

Runs are in-memory only (the final report is persisted separately by
`log_report` / stored summaries).
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from langgraph.types import Command

from app.config import settings
from app.graph import events
from app.logstore import log_report
from app.models import FinalReport

logger = logging.getLogger("runs")


class RunPoolFull(Exception):
    """Raised by `start()` when the run pool and its backlog are saturated.

    The API turns this into HTTP 429 (Too Many Requests) so callers back off
    rather than the server fanning out unbounded concurrent LLM calls.
    """


@dataclass
class Run:
    run_id: str
    ticker: str
    status: str = "running"  # running | waiting_input | done | error
    question: dict | None = None
    report: FinalReport | None = None
    error: str | None = None
    finished_at: float | None = None  # monotonic-ish wall clock for TTL sweep
    lock: threading.Lock = field(default_factory=threading.Lock)


class RunManager:
    def __init__(self, graph, *, max_workers: int | None = None,
                 max_queued: int | None = None) -> None:
        self._graph = graph
        self._runs: dict[str, Run] = {}
        self._max_workers = max_workers or settings.run_max_workers
        max_queued = max_queued if max_queued is not None else settings.run_max_queued
        # Hard ceiling on runs that are executing OR waiting for a worker.
        self._max_inflight = self._max_workers + max_queued
        self._executor = ThreadPoolExecutor(
            max_workers=self._max_workers, thread_name_prefix="run"
        )
        self._pool_lock = threading.Lock()
        self._active = 0    # currently executing agents
        self._pending = 0   # active + queued (submitted, not yet finished)

    def get(self, run_id: str) -> Run | None:
        return self._runs.get(run_id)

    def start(
        self,
        ticker: str,
        depth: str | None,
        lens: str | None,
        portfolio_context: dict | None = None,
    ) -> str:
        with self._pool_lock:
            if self._pending >= self._max_inflight:
                raise RunPoolFull(
                    "The research queue is full; please retry in a moment."
                )
        run_id = uuid.uuid4().hex[:12]
        run = Run(run_id=run_id, ticker=ticker)
        events.register(run_id)
        self._runs[run_id] = run

        payload: dict = {"run_id": run_id, "ticker": ticker}
        if depth:
            payload["depth"] = depth
        if lens:
            payload["lens"] = lens
        if portfolio_context:
            # Phase 3: snapshot of the user's holdings/preferences; the planner
            # sees it and adds the Portfolio Manager Agent to the plan.
            payload["portfolio_context"] = portfolio_context
        self._submit(run, payload)
        return run_id

    def answer(self, run_id: str, answer: str) -> bool:
        run = self._runs.get(run_id)
        if run is None or run.status != "waiting_input":
            return False
        run.status = "running"
        run.question = None
        # Resume is not subject to the intake cap — the run already holds a slot
        # conceptually; it just needs a worker to pick the checkpoint back up.
        self._submit(run, Command(resume=answer))
        return True

    def sweep(self, ttl_minutes: int | None = None) -> int:
        """Evict runs that finished more than `ttl_minutes` ago. Returns count.

        Called on an interval by the scheduler (Phase 1.3). Dropping the Run
        and its event history is what keeps memory flat; `GET /research/{id}`
        then 404s, which is fine — the report is already persisted.
        """
        ttl = (ttl_minutes if ttl_minutes is not None
               else settings.run_ttl_minutes) * 60
        cutoff = time.time() - ttl
        evicted = 0
        for run_id, run in list(self._runs.items()):
            if run.status in ("done", "error") and run.finished_at is not None \
                    and run.finished_at < cutoff:
                self._runs.pop(run_id, None)
                events.unregister(run_id)
                evicted += 1
        if evicted:
            logger.info("swept %d finished run(s)", evicted)
        return evicted

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    # -- internals ------------------------------------------------------------
    def _submit(self, run: Run, graph_input) -> None:
        with self._pool_lock:
            queued = self._active >= self._max_workers
            self._pending += 1
        if queued:
            # No free worker: tell the UI the run is waiting rather than stalled.
            events.emit(run.run_id, {
                "type": "queued",
                "message": "Waiting for an available worker…",
            })
        self._executor.submit(self._run_execute, run, graph_input)

    def _run_execute(self, run: Run, graph_input) -> None:
        with self._pool_lock:
            self._active += 1
        try:
            self._execute(run, graph_input)
        finally:
            with self._pool_lock:
                self._active -= 1
                self._pending -= 1

    def _execute(self, run: Run, graph_input) -> None:
        config = {"configurable": {"thread_id": run.run_id}}
        try:
            result = self._graph.invoke(graph_input, config)
        except Exception as exc:  # noqa: BLE001
            logger.exception("run %s failed", run.run_id)
            with run.lock:
                run.status = "error"
                run.error = str(exc)
                run.finished_at = time.time()
            events.emit(run.run_id, {"type": "error", "message": str(exc)[:300]})
            return

        interrupts = result.get("__interrupt__") if isinstance(result, dict) else None
        if interrupts:
            payload = interrupts[0].value
            if not isinstance(payload, dict):
                payload = {"question": str(payload)}
            with run.lock:
                run.status = "waiting_input"
                run.question = payload
            events.emit(run.run_id, {"type": "question", **payload})
            return

        report = result.get("final_report")
        with run.lock:
            run.status = "done"
            run.report = report
            run.finished_at = time.time()
        if report is not None:
            log_report(report)
            events.emit(run.run_id, {"type": "report",
                                     "report": report.model_dump()})
        events.emit(run.run_id, {"type": "done"})

    async def sse_events(self, run_id: str):
        """Async generator yielding SSE frames until the run finishes.

        Stays open across interrupts: a 'question' event is emitted, the
        client answers via POST, and progress resumes on the same stream.
        Replays the run's full event history, so late subscribers and
        reconnects see every event exactly once. Being async, it awaits the
        event bus instead of blocking an AnyIO threadpool thread (Phase 1.1).
        """
        if self._runs.get(run_id) is None:
            return
        index = 0
        while True:
            event = await events.get(run_id, index, timeout=15.0)
            if event is None:
                # Timeout keepalive, unless the run was evicted out from under us.
                if self._runs.get(run_id) is None:
                    return
                yield ": keepalive\n\n"
                continue
            index += 1
            yield _frame(event)
            if event.get("type") in ("done", "error"):
                return


def _frame(event: dict) -> str:
    import json

    return f"data: {json.dumps(event, default=str)}\n\n"
