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

// Live valuation: current prices, gain/loss, and a portfolio value series.
// period: "1mo" | "3mo" | "6mo" | "1y" | "2y" | "5y"
export const getPortfolioValuation = (period = "6mo") =>
  request(`/portfolio/valuation?period=${encodeURIComponent(period)}`);

export const getPreferences = () => request("/preferences");

export const savePreferences = (prefs) =>
  request("/preferences", { method: "PUT", body: prefs });

// --- Phase 4: watchlist -----------------------------------------------------------

export const getWatchlist = () => request("/watchlist");

export const addToWatchlist = (ticker, note) =>
  request("/watchlist", { method: "POST", body: { ticker, note: note || null } });

export const removeFromWatchlist = (id) =>
  request(`/watchlist/${id}`, { method: "DELETE" });

// --- Phase 4: daily summaries -------------------------------------------------------

// latest=true dedupes to the newest summary per ticker (the feed view).
export const getSummaries = (ticker, { latest = false } = {}) => {
  const params = new URLSearchParams();
  if (ticker) params.set("ticker", ticker);
  if (latest) params.set("latest", "true");
  const qs = params.toString();
  return request(`/summaries${qs ? `?${qs}` : ""}`);
};

// Full stored report — viewable without re-running agents.
export const getSummary = (id) => request(`/summaries/${id}`);

// Start a run-now sweep (same code path as the nightly job). Returns a job
// object immediately: {job_id, status, total, completed, current, tickers}.
// mode: "missing" = only tickers with no summary yet today (cheap — covers
// newly added holdings); "all" = re-run everything.
export const runSummariesNow = (mode = "all") =>
  request(`/summaries/run?mode=${encodeURIComponent(mode)}`, { method: "POST" });

// Poll a run-now job's progress.
export const getSummaryRunStatus = (jobId) =>
  request(`/summaries/run/${encodeURIComponent(jobId)}`);

// --- Phase 4: email digest of the daily feed --------------------------------------------

export const getDigestPrefs = () => request("/digest");

// prefs: {enabled, frequency: "daily"|"weekly"|"monthly", weekday: 0-6|null}
export const saveDigestPrefs = (prefs) =>
  request("/digest", { method: "PUT", body: prefs });

// Email the digest immediately (preview what the schedule will send).
export const sendDigestNow = () =>
  request("/digest/send-now", { method: "POST" });

// --- Phase 4: alerts & notifications --------------------------------------------------

export const getAlertRules = () => request("/alerts");

export const saveAlertRule = (rule) =>
  request("/alerts", { method: "POST", body: rule });

export const deleteAlertRule = (id) =>
  request(`/alerts/${id}`, { method: "DELETE" });

export const getNotifications = (unreadOnly = false) =>
  request(`/notifications${unreadOnly ? "?unread_only=true" : ""}`);

export const getUnreadCount = () => request("/notifications/unread-count");

export const markNotificationRead = (id) =>
  request(`/notifications/${id}/read`, { method: "POST" });

export const markAllNotificationsRead = () =>
  request("/notifications/read-all", { method: "POST" });

// --- Calibration (Phase 4: how well past confidence matched outcomes) --------------

export const getCalibration = () => request("/calibration");

// --- Recommendations (global top-10 board) -----------------------------------------

export const getRecommendations = () => request("/recommendations");

// Kick off a sweep: screen S&P 500 + Nasdaq-100, agent-analyze survivors.
// Returns a job dict immediately: {job_id, status, phase, completed, total}.
export const runRecommendationsNow = () =>
  request("/recommendations/run", { method: "POST" });

export const getRecommendationsRunStatus = (jobId) =>
  request(`/recommendations/run/${encodeURIComponent(jobId)}`);

// Currently running sweep, if any. Lets a freshly mounted panel re-attach
// its progress bar after a tab switch instead of re-enabling the button.
export const getActiveRecommendationsRun = () =>
  request("/recommendations/active");

// --- Learn (stock-of-the-day video) -------------------------------------------------

export const getStockOfTheDay = () => request("/learn/stock-of-the-day");

// The full latest top-10 in rank order (pick-a-stock list).
export const getLearnPicks = () => request("/learn/picks");

// A random different stock from the latest top 10 ("another stock" button).
export const getLearnShuffle = (exclude) =>
  request(`/learn/shuffle${exclude ? `?exclude=${encodeURIComponent(exclude)}` : ""}`);

// Kick off a Remotion MP4 render on the server for the given ticker (or the
// daily pick when omitted) at 30s or 65s. Returns {job_id, status, phase}.
export const startLearnRender = (ticker, durationSec = 30) =>
  request("/learn/render", {
    method: "POST",
    body: { ticker: ticker || null, duration_sec: durationSec },
  });

export const getLearnRenderStatus = (jobId) =>
  request(`/learn/render/${encodeURIComponent(jobId)}`);

// Generate (or reuse) the narration voiceover for a pick so the in-app preview
// can play it. Returns {available, engine, dir, scenes}.
export const makeLearnVoiceover = (ticker, durationSec = 30) =>
  request("/learn/voiceover", {
    method: "POST",
    body: { ticker: ticker || null, duration_sec: durationSec },
  });

// Fetch the finished MP4 (auth header required) and trigger a download.
export async function downloadLearnVideo(jobId, filename) {
  const res = await fetch(
    `/learn/render/${encodeURIComponent(jobId)}/file`,
    { headers: authHeaders() }
  );
  if (!res.ok) throw new Error(`Download failed (${res.status})`);
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename || "stock-of-the-day.mp4";
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

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
  // EventSource can't set an Authorization header, so pass the JWT as a query
  // param — the backend needs it to authorize the stream of a user-bound run.
  const auth = getAuth();
  const q = auth ? `?token=${encodeURIComponent(auth.token)}` : "";
  const es = new EventSource(`/research/${encodeURIComponent(runId)}/events${q}`);
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
