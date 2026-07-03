"""Run lifecycle manager.

Executes the LangGraph in a worker thread per run, bridges node progress
events to an SSE-consumable queue, and handles the planner's interrupt/resume
cycle:

  start()  → invoke(graph)      → done | waiting_input (interrupt surfaced)
  answer() → invoke(Command(resume=...)) picks up from the checkpoint

Runs are in-memory only (no persistence — per Phase 2 scope).
"""
from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import dataclass, field

from langgraph.types import Command

from app.graph import events
from app.logstore import log_report
from app.models import FinalReport

logger = logging.getLogger("runs")


@dataclass
class Run:
    run_id: str
    ticker: str
    status: str = "running"  # running | waiting_input | done | error
    question: dict | None = None
    report: FinalReport | None = None
    error: str | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)


class RunManager:
    def __init__(self, graph) -> None:
        self._graph = graph
        self._runs: dict[str, Run] = {}

    def get(self, run_id: str) -> Run | None:
        return self._runs.get(run_id)

    def start(self, ticker: str, depth: str | None, lens: str | None) -> str:
        run_id = uuid.uuid4().hex[:12]
        run = Run(run_id=run_id, ticker=ticker)
        events.register(run_id)
        self._runs[run_id] = run

        payload: dict = {"run_id": run_id, "ticker": ticker}
        if depth:
            payload["depth"] = depth
        if lens:
            payload["lens"] = lens
        self._spawn(run, payload)
        return run_id

    def answer(self, run_id: str, answer: str) -> bool:
        run = self._runs.get(run_id)
        if run is None or run.status != "waiting_input":
            return False
        run.status = "running"
        run.question = None
        self._spawn(run, Command(resume=answer))
        return True

    # -- internals ------------------------------------------------------------
    def _spawn(self, run: Run, graph_input) -> None:
        threading.Thread(
            target=self._execute, args=(run, graph_input), daemon=True
        ).start()

    def _execute(self, run: Run, graph_input) -> None:
        config = {"configurable": {"thread_id": run.run_id}}
        try:
            result = self._graph.invoke(graph_input, config)
        except Exception as exc:  # noqa: BLE001
            logger.exception("run %s failed", run.run_id)
            with run.lock:
                run.status = "error"
                run.error = str(exc)
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
        if report is not None:
            log_report(report)
            events.emit(run.run_id, {"type": "report",
                                     "report": report.model_dump()})
        events.emit(run.run_id, {"type": "done"})

    def sse_events(self, run_id: str):
        """Generator yielding SSE frames until the run finishes.

        Stays open across interrupts: a 'question' event is emitted, the
        client answers via POST, and progress resumes on the same stream.
        Replays the run's full event history, so late subscribers and
        reconnects see every event exactly once.
        """
        if self._runs.get(run_id) is None:
            return
        index = 0
        while True:
            event = events.get(run_id, index, timeout=15.0)
            if event is None:
                yield ": keepalive\n\n"
                continue
            index += 1
            yield _frame(event)
            if event.get("type") in ("done", "error"):
                return


def _frame(event: dict) -> str:
    import json

    return f"data: {json.dumps(event, default=str)}\n\n"
