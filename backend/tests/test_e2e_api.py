"""End-to-end API test: start → SSE progress → clarifying question → answer →
resumed run → grouped final report. Uses fake providers (no keys) and a real
uvicorn server on localhost (TestClient buffers infinite SSE streams, so a
real server is required to exercise streaming).

Run: cd backend && python -m tests.test_e2e_api
"""
from __future__ import annotations

import json
import threading
import time

import httpx
import uvicorn

import app.main as main
from app.runs import RunManager
from tests.test_phase2 import make_graph

PORT = 8899
BASE = f"http://127.0.0.1:{PORT}"


def _start_server() -> uvicorn.Server:
    main.runs = RunManager(make_graph())  # fake tools — no keys/network
    config = uvicorn.Config(main.app, host="127.0.0.1", port=PORT, log_level="warning")
    server = uvicorn.Server(config)
    threading.Thread(target=server.run, daemon=True).start()
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            if httpx.get(f"{BASE}/health", timeout=1.0).status_code == 200:
                return server
        except httpx.HTTPError:
            time.sleep(0.1)
    raise RuntimeError("server did not start")


def _collect_events(run_id: str, out: list) -> None:
    with httpx.stream("GET", f"{BASE}/research/{run_id}/events", timeout=60.0) as resp:
        for line in resp.iter_lines():
            if not line.startswith("data: "):
                continue
            event = json.loads(line[len("data: "):])
            out.append(event)
            if event["type"] in ("done", "error"):
                return


def test_full_run_with_questions():
    server = _start_server()
    events: list = []

    r = httpx.post(f"{BASE}/research", json={"ticker": "msft"})  # planner will ask
    assert r.status_code == 200, r.text
    run_id = r.json()["run_id"]

    t = threading.Thread(target=_collect_events, args=(run_id, events), daemon=True)
    t.start()

    def wait_for(evt_type: str, after: int = 0, timeout: float = 15.0) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            for e in events[after:]:
                if e["type"] == evt_type:
                    return e
            time.sleep(0.05)
        raise AssertionError(f"timed out waiting for {evt_type}; got {events}")

    # Question 1: depth. Answer over plain POST; the SSE stream stays open.
    q1 = wait_for("question")
    assert "quick" in q1["options"] and "deep" in q1["options"]
    n = len(events)
    r = httpx.post(f"{BASE}/research/{run_id}/answer", json={"answer": "deep"})
    assert r.status_code == 200

    # Question 2: lens (deep dives only).
    q2 = wait_for("question", after=n)
    assert "growth" in q2["options"]
    r = httpx.post(f"{BASE}/research/{run_id}/answer", json={"answer": "growth"})
    assert r.status_code == 200

    wait_for("done", timeout=30)
    t.join(timeout=5)

    types = [e["type"] for e in events]
    assert types.count("question") == 2
    assert "plan" in types and "report" in types

    report = next(e for e in events if e["type"] == "report")["report"]
    assert report["ticker"] == "MSFT"
    assert report["depth"] == "deep" and report["lens"] == "growth"
    assert [a["agent"] for a in report["agent_reports"]] == [
        "news", "financials", "technicals", "valuation",
    ]
    assert report["recommendation"]["stance"] == "bullish"
    statuses = [e for e in events if e["type"] == "status"]
    assert any(s["agent"] == "financials" and s["state"] == "done" for s in statuses)

    # Answering a run that isn't waiting → 409.
    r = httpx.post(f"{BASE}/research/{run_id}/answer", json={"answer": "x"})
    assert r.status_code == 409

    # Poll fallback endpoint reports the finished run.
    r = httpx.get(f"{BASE}/research/{run_id}")
    assert r.json()["status"] == "done" and r.json()["report"] is not None

    server.should_exit = True
    print("✓ e2e: SSE progress, two clarifying questions, resumed run, grouped report")


if __name__ == "__main__":
    test_full_run_with_questions()
    print("\nE2E API test passed.")
