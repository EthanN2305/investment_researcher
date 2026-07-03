// Thin API client for Phase 2 runs. Same-origin paths; Vite proxies /research
// and /health to the FastAPI backend in dev (see vite.config.js).

async function jsonOrThrow(res) {
  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      if (body?.detail) detail = body.detail;
    } catch {
      /* non-JSON error body */
    }
    throw new Error(detail);
  }
  return res.json();
}

// Start a research run. Returns { run_id, ticker }.
export async function startResearch(ticker, { depth, lens } = {}) {
  const res = await fetch("/research", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ticker, depth: depth || null, lens: lens || null }),
  });
  return jsonOrThrow(res);
}

// Answer the planner's clarifying question; the paused run resumes.
export async function answerQuestion(runId, answer) {
  const res = await fetch(`/research/${encodeURIComponent(runId)}/answer`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ answer }),
  });
  return jsonOrThrow(res);
}

// Subscribe to a run's SSE stream. `onEvent` receives parsed event objects
// ({type: "plan" | "status" | "question" | "report" | "error" | "done", ...}).
// Returns a close() function. The stream stays open across clarifying
// questions — answers go via POST, progress keeps flowing here.
export function subscribeToRun(runId, onEvent, onConnectionError) {
  const es = new EventSource(`/research/${encodeURIComponent(runId)}/events`);
  es.onmessage = (msg) => {
    try {
      const event = JSON.parse(msg.data);
      onEvent(event);
      if (event.type === "done" || event.type === "error") es.close();
    } catch {
      /* keepalive or malformed frame — ignore */
    }
  };
  es.onerror = () => {
    // EventSource auto-reconnects; only surface if it's fully closed.
    if (es.readyState === EventSource.CLOSED && onConnectionError) {
      onConnectionError(new Error("Lost connection to the research run."));
    }
  };
  return () => es.close();
}
