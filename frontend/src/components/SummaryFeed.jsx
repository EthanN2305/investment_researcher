import { useEffect, useRef, useState } from "react";
import {
  getSummaries,
  getSummary,
  getSummaryRunStatus,
  runSummariesNow,
} from "../api.js";
import ReportView from "./ReportView.jsx";

const POLL_MS = 1000;

// Progress of a run-now sweep: one segment per ticker, plus a label for the
// ticker whose agents are currently running.
function RunProgress({ job }) {
  const { total, completed, current, tickers = [] } = job;
  // Give the in-flight ticker half a segment so the bar visibly moves as
  // soon as work starts, not only when a ticker finishes.
  const pct = total > 0
    ? Math.round(((completed + (current ? 0.5 : 0)) / total) * 100)
    : 0;

  return (
    <div className="run-progress" role="status" aria-live="polite">
      <div className="run-progress-row">
        <span className="run-progress-label">
          {current
            ? `Researching ${current}…`
            : completed < total
              ? "Starting…"
              : "Finishing up…"}
        </span>
        <span className="run-progress-count">
          {completed} / {total} tickers
        </span>
      </div>
      <div
        className="progress-track"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={pct}
      >
        <div className="progress-fill" style={{ width: `${pct}%` }} />
      </div>
      {tickers.length > 1 && (
        <div className="run-progress-tickers">
          {tickers.map((t, i) => (
            <span
              key={t}
              className={
                i < completed
                  ? "run-ticker done"
                  : t === current
                    ? "run-ticker active"
                    : "run-ticker"
              }
            >
              {t}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

// Daily summary feed: short stored blurbs, each expandable to the full
// structured report — no agents re-run on open.
function SummaryCard({ item }) {
  const [full, setFull] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function toggle() {
    if (full) {
      setFull(null);
      return;
    }
    setLoading(true);
    setError("");
    try {
      setFull(await getSummary(item.id));
    } catch (err) {
      setError(err.message || "Could not load the full report.");
    } finally {
      setLoading(false);
    }
  }

  const pct = Math.round((item.confidence ?? 0) * 100);
  return (
    <li className="summary-card">
      <div className="summary-head">
        <span className="ticker-cell">{item.ticker}</span>
        <span className={`stance ${item.stance}`}>
          {item.stance} · {pct}%
        </span>
        <span className="summary-meta">
          {item.trigger === "manual" ? "manual run" : "daily"} ·{" "}
          {item.created_at ? new Date(item.created_at).toLocaleString() : ""}
        </span>
      </div>
      <p className="summary-text">{item.summary}</p>
      <button type="button" className="linklike" onClick={toggle}>
        {loading ? "Loading…" : full ? "Hide full report" : "View full report"}
      </button>
      {error && <p className="auth-error" role="alert">{error}</p>}
      {full && (
        <div className="summary-full-report">
          <ReportView report={full.report} />
        </div>
      )}
    </li>
  );
}

export default function SummaryFeed() {
  const [items, setItems] = useState(null); // null = loading
  const [job, setJob] = useState(null); // running job progress | null
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const pollRef = useRef(null);

  async function refresh() {
    try {
      // latest=true → one card per ticker (its newest summary), so re-runs
      // replace entries instead of stacking duplicates.
      setItems(await getSummaries(null, { latest: true }));
    } catch (err) {
      setError(err.message || "Could not load summaries.");
    }
  }

  useEffect(() => {
    refresh();
    return () => clearInterval(pollRef.current);
  }, []);

  function finishJob(finalJob) {
    clearInterval(pollRef.current);
    pollRef.current = null;
    setJob(null);
    if (finalJob.status === "error") {
      setError(finalJob.error || "The summary run failed.");
    }
    refresh();
  }

  // mode: "missing" — only tickers with no summary yet today (covers newly
  // added holdings without re-spending tokens on the rest); "all" — full re-run.
  async function onRunNow(mode) {
    setError("");
    setNotice("");
    try {
      const started = await runSummariesNow(mode);
      if (started.total === 0) {
        setNotice(
          "Feed is already up to date — every holding has a summary today. " +
            'Use "Rerun all" to refresh them.'
        );
        return;
      }
      setJob(started);
      if (started.status !== "running") {
        finishJob(started);
        return;
      }
      pollRef.current = setInterval(async () => {
        try {
          const next = await getSummaryRunStatus(started.job_id);
          setJob(next);
          if (next.status !== "running") finishJob(next);
        } catch (err) {
          clearInterval(pollRef.current);
          pollRef.current = null;
          setJob(null);
          setError(err.message || "Lost track of the summary run.");
        }
      }, POLL_MS);
    } catch (err) {
      setError(err.message || "Could not start the summary run.");
    }
  }

  const running = job !== null;

  return (
    <section className="panel">
      <div className="panel-head-row">
        <h3>Daily summaries</h3>
        <div className="panel-actions">
          <button
            type="button"
            onClick={() => onRunNow("missing")}
            disabled={running}
            title="Only summarizes holdings that don't have a summary yet today (e.g. ones you just added) — existing summaries stay put."
          >
            {running ? "Running agents…" : "Update feed"}
          </button>
          <button
            type="button"
            onClick={() => onRunNow("all")}
            disabled={running}
            title="Re-runs the agents for every watched and held ticker, including newly added ones."
          >
            Rerun all
          </button>
        </div>
      </div>
      <p className="panel-note">
        The pipeline runs automatically once a day for every watched and held
        ticker; results are stored so you can read them here without re-running
        agents. "Update feed" only summarizes holdings missing from today's
        feed (token-cheap); "Rerun all" refreshes everything.
      </p>
      {job && <RunProgress job={job} />}
      {notice && <p className="panel-note" role="status">{notice}</p>}
      {error && <p className="auth-error" role="alert">{error}</p>}

      {items === null ? (
        <p className="empty">Loading feed…</p>
      ) : items.length === 0 ? (
        <p className="empty">
          No summaries yet — add tickers to your watchlist or portfolio, then
          wait for the daily run (or press "Run now").
        </p>
      ) : (
        <ul className="summary-feed">
          {items.map((s) => (
            <SummaryCard key={s.id} item={s} />
          ))}
        </ul>
      )}
    </section>
  );
}
