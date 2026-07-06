import { useEffect, useRef, useState } from "react";
import {
  getActiveRecommendationsRun,
  getRecommendations,
  getRecommendationsRunStatus,
  runRecommendationsNow,
} from "../api.js";

const POLL_MS = 2000;

const money = (n) =>
  n == null
    ? "—"
    : n.toLocaleString(undefined, {
        style: "currency",
        currency: "USD",
        maximumFractionDigits: 2,
      });

const pct = (n) => (n == null ? "—" : `${n > 0 ? "+" : ""}${(n * 100).toFixed(1)}%`);

const STANCE_LABEL = { bullish: "BULLISH", neutral: "NEUTRAL", bearish: "BEARISH" };

function stanceClass(stance) {
  return stance === "bullish"
    ? "badge-signal badge-buy"
    : stance === "bearish"
      ? "badge-signal badge-sell"
      : "badge-signal badge-hold";
}

function confColor(c) {
  return c >= 0.7 ? "var(--green)" : c >= 0.45 ? "var(--amber)" : "var(--red)";
}

export default function RecommendationsPanel({ onResearch }) {
  const [data, setData] = useState(null); // {run_id, created_at, items, universe_size}
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [job, setJob] = useState(null); // running sweep progress
  const [starting, setStarting] = useState(false); // click → job attached
  const pollRef = useRef(null);

  useEffect(() => {
    load();
    // A sweep is global and may still be running from a previous tab visit —
    // re-attach the progress bar instead of showing an enabled button.
    getActiveRecommendationsRun()
      .then((active) => {
        if (active && active.status === "running" && active.job_id) {
          setJob(active);
          startPolling(active.job_id);
        }
      })
      .catch(() => {
        /* no active run / transient failure — ignore */
      });
    return () => clearInterval(pollRef.current);
  }, []);

  function load() {
    setLoading(true);
    getRecommendations()
      .then(setData)
      .catch((e) => setError(e.message || "Could not load recommendations."))
      .finally(() => setLoading(false));
  }

  function startPolling(jobId) {
    clearInterval(pollRef.current);
    pollRef.current = setInterval(async () => {
      try {
        const status = await getRecommendationsRunStatus(jobId);
        setJob(status);
        if (status.status !== "running") {
          clearInterval(pollRef.current);
          setJob(null);
          if (status.status === "error") {
            setError(status.error || "The sweep failed.");
          } else {
            load();
          }
        }
      } catch {
        /* transient poll failure — keep trying */
      }
    }, POLL_MS);
  }

  async function onRefresh() {
    if (starting || job) return; // guard double-clicks before state settles
    setError("");
    setStarting(true);
    try {
      const started = await runRecommendationsNow();
      setJob(started);
      startPolling(started.job_id);
    } catch (err) {
      setError(err.message || "Could not start the sweep.");
    } finally {
      setStarting(false);
    }
  }

  const items = data?.items || [];
  const running = job != null;
  const busy = running || starting;
  const progressPct = job?.total
    ? Math.round((job.completed / job.total) * 100)
    : 0;

  return (
    <section className="panel">
      <div className="panel-head-row">
        <h3>Top 10 recommendations</h3>
        <button type="button" onClick={onRefresh} disabled={busy} aria-busy={busy}>
          {busy ? "Sweeping…" : items.length ? "Refresh picks" : "Generate picks"}
        </button>
      </div>
      <p className="panel-note">
        Screened from {data?.universe_size ?? "~520"} S&amp;P 500 and
        Nasdaq-100 stocks (no penny stocks), then ranked by the technical and
        valuation agents' stance and confidence.
        {data?.created_at &&
          ` Last updated ${new Date(data.created_at).toLocaleString()}.`}
      </p>

      {running && (
        <div className="run-progress">
          <div className="run-progress-row">
            <span className="run-progress-label">
              {job.phase === "screening"
                ? "Screening universe…"
                : job.current
                  ? `Agents analyzing ${job.current}…`
                  : "Analyzing candidates…"}
            </span>
            <span className="run-progress-count">
              {job.completed}/{job.total}
            </span>
          </div>
          <div className="progress-track">
            <div
              className="progress-fill"
              style={{ width: `${progressPct}%` }}
            ></div>
          </div>
        </div>
      )}

      {error && <p className="auth-error" role="alert">{error}</p>}

      {loading ? (
        <div className="loading">
          <span className="spinner" aria-hidden="true"></span>
          Loading recommendations…
        </div>
      ) : items.length === 0 && !running ? (
        <p className="empty">
          No recommendations yet — hit "Generate picks" to screen the market
          and let the agents rank the top 10. Takes a couple of minutes.
        </p>
      ) : (
        <ol className="recs-list">
          {items.map((r) => (
            <li key={r.rank} className="rec-card">
              <span className="rec-rank">#{r.rank}</span>
              <div className="rec-main">
                <div className="rec-head">
                  <span className="ticker-cell rec-ticker">{r.ticker}</span>
                  <span className={stanceClass(r.stance)}>
                    {STANCE_LABEL[r.stance] || r.stance}
                  </span>
                  <span className="rec-price">{money(r.price)}</span>
                  <span
                    className={
                      (r.momentum_3mo ?? 0) >= 0 ? "rec-mom pos" : "rec-mom neg"
                    }
                    title="3-month price momentum"
                  >
                    {pct(r.momentum_3mo)} / 3mo
                  </span>
                </div>
                <p className="rec-summary">{r.summary}</p>
                <div className="rec-foot">
                  <div className="confidence-row">
                    <div className="conf-track rec-conf-track">
                      <span
                        className="conf-fill"
                        style={{
                          width: `${Math.round(r.confidence * 100)}%`,
                          background: confColor(r.confidence),
                        }}
                      ></span>
                    </div>
                    <span className="conf-pct" style={{ color: confColor(r.confidence) }}>
                      {Math.round(r.confidence * 100)}% confidence
                    </span>
                  </div>
                  {onResearch && (
                    <button
                      type="button"
                      className="linklike"
                      onClick={() => onResearch(r.ticker)}
                    >
                      Deep dive →
                    </button>
                  )}
                </div>
              </div>
            </li>
          ))}
        </ol>
      )}

      <p className="disclaimer">
        Recommendations are generated by automated screens and agent models —
        informational only, not investment advice.
      </p>
    </section>
  );
}
