// Thin API client. Same-origin paths; Vite proxies /research, /auth,
// /portfolio, /preferences and /health to the FastAPI backend in dev.
//
// Phase 3: JWT bearer auth. The token lives in localStorage; every request
// attaches it when present, so /research runs are personalized automatically.

const TOKEN_KEY = "auth_token";
const EMAIL_KEY = "auth_email";

export function getAuth() {
  const token = localStorage.getItem(TOKEN_KEY);
  const email = localStorage.getItem(EMAIL_KEY);
  return token ? { token, email } : null;
}

export function setAuth(token, email) {
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.setItem(EMAIL_KEY, email);
}

export function clearAuth() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(EMAIL_KEY);
}

function authHeaders() {
  const auth = getAuth();
  return auth ? { Authorization: `Bearer ${auth.token}` } : {};
}

async function jsonOrThrow(res) {
  if (res.status === 401 && getAuth()) {
    // Token expired/invalid — drop it so the UI falls back to logged-out.
    clearAuth();
  }
  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      if (body?.detail) {
        detail = typeof body.detail === "string"
          ? body.detail
          : body.detail[0]?.msg || detail;
      }
    } catch {
      /* non-JSON error body */
    }
    throw new Error(detail);
  }
  if (res.status === 204) return null;
  return res.json();
}

function request(path, { method = "GET", body } = {}) {
  return fetch(path, {
    method,
    headers: {
      ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
      ...authHeaders(),
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  }).then(jsonOrThrow);
}

// --- Auth --------------------------------------------------------------------

export async function signup(email, password) {
  const data = await request("/auth/signup", {
    method: "POST", body: { email, password },
  });
  setAuth(data.access_token, data.email);
  return data;
}

export async function login(email, password) {
  const data = await request("/auth/login", {
    method: "POST", body: { email, password },
  });
  setAuth(data.access_token, data.email);
  return data;
}

// --- Portfolio & preferences ---------------------------------------------------

export const getHoldings = () => request("/portfolio");

export const saveHolding = (holding) =>
  request("/portfolio", { method: "POST", body: holding });

export const deleteHolding = (id) =>
  request(`/portfolio/${id}`, { method: "DELETE" });

export const getPreferences = () => request("/preferences");

export const savePreferences = (prefs) =>
  request("/preferences", { method: "PUT", body: prefs });

// --- Research runs ---------------------------------------------------------------

// Start a research run. Personalizes automatically when logged in.
// Returns { run_id, ticker, personalized }.
export function startResearch(ticker, { depth, lens, personalize = true } = {}) {
  return request("/research", {
    method: "POST",
    body: { ticker, depth: depth || null, lens: lens || null, personalize },
  });
}

// Answer the planner's clarifying question; the paused run resumes.
export function answerQuestion(runId, answer) {
  return request(`/research/${encodeURIComponent(runId)}/answer`, {
    method: "POST", body: { answer },
  });
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
