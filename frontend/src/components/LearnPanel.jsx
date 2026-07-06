// Learn tab — "stock of the day" video, randomly picked (date-seeded)
// from the latest recommendations sweep. Previews live via the Remotion
// <Player>; "Download" asks the backend to render a real 1080x1920 MP4
// with the same composition and props.
//
// The user can also pick any stock from the latest top-10 (e.g. "#2 of the
// day") and choose the video length: 30s or 1m05s.
import { useEffect, useRef, useState } from "react";
import { Player } from "@remotion/player";
import {
  downloadLearnVideo,
  getLearnPicks,
  getLearnRenderStatus,
  getLearnShuffle,
  getStockOfTheDay,
  startLearnRender,
} from "../api.js";
import StockVideo, {
  FPS,
  videoDurationInFrames,
} from "../video/StockVideo.jsx";

const POLL_MS = 2500;

const PHASE_LABEL = {
  starting: "Starting render…",
  browser: "Setting up renderer…",
  bundling: "Bundling video…",
  rendering: "Rendering frames…",
};

const DURATIONS = [
  { sec: 30, label: "30 sec" },
  { sec: 65, label: "1 min 5 sec" },
];

const durationLabel = (sec) => (sec === 65 ? "1m05s" : `${sec}s`);

export default function LearnPanel() {
  const [pick, setPick] = useState(null);
  const [daily, setDaily] = useState(null); // today's date-seeded pick
  const [picks, setPicks] = useState([]); // full latest top-10
  const [duration, setDuration] = useState(30); // seconds: 30 | 65
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [job, setJob] = useState(null); // running render job
  const [downloaded, setDownloaded] = useState(false);
  const [shuffling, setShuffling] = useState(false);
  const [copied, setCopied] = useState(""); // "title" | "description" | ""
  const pollRef = useRef(null);

  async function copyText(text, which) {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(which);
      setTimeout(() => setCopied(""), 1800);
    } catch {
      /* clipboard blocked — user can still select the text manually */
    }
  }

  useEffect(() => {
    Promise.all([
      getStockOfTheDay(),
      getLearnPicks().catch(() => []), // list is optional sugar — never fatal
    ])
      .then(([today, list]) => {
        setDaily(today);
        setPick(today);
        setPicks(list || []);
      })
      .catch((e) => setError(e.message || "Could not load the stock of the day."))
      .finally(() => setLoading(false));
    return () => clearInterval(pollRef.current);
  }, []);

  function selectPick(next) {
    if (!next || next.ticker === pick?.ticker) return;
    setError("");
    setDownloaded(false);
    setCopied("");
    setPick(next);
  }

  async function onShuffle() {
    setError("");
    setDownloaded(false);
    setShuffling(true);
    try {
      const next = await getLearnShuffle(pick?.ticker);
      setPick(next);
    } catch (err) {
      setError(err.message || "Could not pick another stock.");
    } finally {
      setShuffling(false);
    }
  }

  async function onDownload() {
    setError("");
    setDownloaded(false);
    try {
      const started = await startLearnRender(pick?.ticker, duration);
      if (started.status === "done") {
        // Cached from an earlier render today — download immediately.
        await downloadLearnVideo(started.job_id, filename());
        setDownloaded(true);
        return;
      }
      setJob(started);
      pollRef.current = setInterval(async () => {
        try {
          const status = await getLearnRenderStatus(started.job_id);
          setJob(status);
          if (status.status !== "running") {
            clearInterval(pollRef.current);
            setJob(null);
            if (status.status === "error") {
              setError(status.error || "The render failed.");
            } else {
              await downloadLearnVideo(status.job_id, filename());
              setDownloaded(true);
            }
          }
        } catch {
          /* transient poll failure — keep trying */
        }
      }, POLL_MS);
    } catch (err) {
      setError(err.message || "Could not start the render.");
    }
  }

  function filename() {
    return pick
      ? `${pick.ticker}-stock-of-the-day-${durationLabel(duration)}-${pick.date}.mp4`
      : "stock-of-the-day.mp4";
  }

  const rendering = job != null;
  const isDaily = daily && pick && pick.ticker === daily.ticker;
  const frames = videoDurationInFrames(duration);

  if (loading) {
    return (
      <section className="panel">
        <div className="loading">
          <span className="spinner" aria-hidden="true"></span>
          Picking today's stock…
        </div>
      </section>
    );
  }

  if (!pick) {
    return (
      <section className="panel">
        <h3>Stock of the day</h3>
        <p className="empty">
          {error ||
            "No recommendations yet — generate picks on the Recommendations tab first, then come back here."}
        </p>
      </section>
    );
  }

  return (
    <section className="panel learn-panel">
      <div className="panel-head-row">
        <h3>Stock of the day</h3>
        <span className="learn-date">{pick.date_label}</span>
      </div>
      <p className="panel-note">
        A {duration === 65 ? "65-second" : "30-second"} brief on{" "}
        <strong>${pick.ticker}</strong> —{" "}
        {isDaily
          ? "today's random pick from the agents' top 10. A new stock drops every day."
          : `your pick: #${pick.rank} from the agents' top 10.`}
      </p>

      <div className="learn-layout">
        <div className="learn-player-wrap">
          <Player
            key={`${pick.ticker}-${duration}`}
            component={StockVideo}
            inputProps={{
              ticker: pick.ticker,
              price: pick.price,
              stance: pick.stance,
              confidence: pick.confidence,
              momentum_3mo: pick.momentum_3mo,
              screen_score: pick.screen_score,
              rank: pick.rank,
              summary: pick.summary,
              date_label: pick.date_label,
              duration_sec: duration,
            }}
            durationInFrames={frames}
            fps={FPS}
            compositionWidth={1080}
            compositionHeight={1920}
            style={{ width: "100%" }}
            controls
            loop
            autoPlay
            initiallyMuted
          />
        </div>

        <div className="learn-side">
          <h4>#{pick.rank} of today's top 10</h4>
          <p className="learn-summary">{pick.summary}</p>

          <div className="learn-duration" role="group" aria-label="Video length">
            <span className="learn-option-label">Length</span>
            {DURATIONS.map((d) => (
              <button
                key={d.sec}
                type="button"
                className={`learn-duration-btn${
                  duration === d.sec ? " active" : ""
                }`}
                onClick={() => {
                  setDuration(d.sec);
                  setDownloaded(false);
                }}
                disabled={rendering}
              >
                {d.label}
              </button>
            ))}
          </div>

          <div className="learn-actions">
            <button
              type="button"
              onClick={onDownload}
              disabled={rendering || shuffling}
              className="learn-download"
            >
              {rendering
                ? PHASE_LABEL[job.phase] || "Rendering…"
                : `Download (${durationLabel(duration)})`}
            </button>
            <button
              type="button"
              onClick={onShuffle}
              disabled={rendering || shuffling}
              className="learn-shuffle"
            >
              {shuffling ? "Picking…" : "🎲 Another stock"}
            </button>
          </div>
          {rendering && (
            <p className="learn-render-note">
              Rendering a 1080×1920 MP4 on the server — usually a minute or
              two. The download starts automatically when it's done.
            </p>
          )}
          {downloaded && (
            <p className="learn-done">
              Saved! Vertical 9:16, {durationLabel(duration)} — ready for
              TikTok and YouTube Shorts.
            </p>
          )}
          {error && (
            <p className="auth-error" role="alert">
              {error}
            </p>
          )}
        </div>
      </div>

      {(pick.title || pick.description) && (
        <div className="learn-caption">
          <h4>Ready-to-post caption</h4>
          <p className="panel-note">
            Copy these into TikTok, YouTube Shorts, or Reels when you upload the
            video.
          </p>

          {pick.title && (
            <div className="learn-caption-field">
              <div className="learn-caption-head">
                <span className="learn-caption-label">Title</span>
                <button
                  type="button"
                  className="learn-copy-btn"
                  onClick={() => copyText(pick.title, "title")}
                >
                  {copied === "title" ? "Copied!" : "Copy"}
                </button>
              </div>
              <p className="learn-caption-title">{pick.title}</p>
            </div>
          )}

          {pick.description && (
            <div className="learn-caption-field">
              <div className="learn-caption-head">
                <span className="learn-caption-label">Description</span>
                <button
                  type="button"
                  className="learn-copy-btn"
                  onClick={() => copyText(pick.description, "description")}
                >
                  {copied === "description" ? "Copied!" : "Copy"}
                </button>
              </div>
              <pre className="learn-caption-desc">{pick.description}</pre>
            </div>
          )}
        </div>
      )}

      {picks.length > 0 && (
        <div className="learn-picks">
          <h4>Or pick any of today's top {picks.length}</h4>
          <ul className="learn-pick-list">
            {picks.map((p) => (
              <li key={p.ticker}>
                <button
                  type="button"
                  className={`learn-pick-btn${
                    p.ticker === pick.ticker ? " active" : ""
                  }`}
                  onClick={() => selectPick(p)}
                  disabled={rendering || shuffling}
                >
                  <span className="learn-pick-rank">#{p.rank}</span>
                  <span className="learn-pick-ticker">${p.ticker}</span>
                  <span className={`learn-pick-stance stance-${p.stance}`}>
                    {p.stance}
                  </span>
                  {daily && p.ticker === daily.ticker && (
                    <span className="learn-pick-today">today's pick</span>
                  )}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      <p className="disclaimer">
        Generated by automated screens and agent models — informational only,
        not investment advice.
      </p>
    </section>
  );
}
