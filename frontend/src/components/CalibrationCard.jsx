import { useEffect, useState } from "react";
import { getCalibration } from "../api.js";
import { AGENT_LABELS } from "./AgentProgress.jsx";

// Phase 4: reliability curve + Brier + per-agent hit rates, computed from
// resolved recommendation outcomes. Shows *earned* calibration, not decoration.
// Renders nothing until there is at least one resolved outcome (honest cold
// start). Hand-rolled inline SVG (no charting dependency), same approach as the
// portfolio donut.
const W = 240;
const H = 240;
const PAD = 28;

function ReliabilityCurve({ points }) {
  // points: [{predicted, observed, count}] in [0,1]. Diagonal = perfect.
  const x = (v) => PAD + v * (W - 2 * PAD);
  const y = (v) => H - PAD - v * (H - 2 * PAD);
  const poly = points
    .slice()
    .sort((a, b) => a.predicted - b.predicted)
    .map((p) => `${x(p.predicted)},${y(p.observed)}`)
    .join(" ");
  return (
    <svg className="reliability-svg" viewBox={`0 0 ${W} ${H}`} role="img"
         aria-label="Reliability curve: predicted vs observed hit rate">
      {/* grid box */}
      <rect x={PAD} y={PAD} width={W - 2 * PAD} height={H - 2 * PAD}
            className="reliability-box" />
      {/* perfect-calibration diagonal */}
      <line x1={x(0)} y1={y(0)} x2={x(1)} y2={y(1)} className="reliability-diag" />
      {/* observed curve */}
      {points.length > 1 && (
        <polyline points={poly} className="reliability-line" fill="none" />
      )}
      {points.map((p, i) => (
        <circle key={i} cx={x(p.predicted)} cy={y(p.observed)}
                r={3 + Math.min(p.count, 8) * 0.4} className="reliability-dot" />
      ))}
      <text x={W / 2} y={H - 6} className="reliability-axis" textAnchor="middle">
        predicted confidence
      </text>
      <text x={10} y={H / 2} className="reliability-axis"
            transform={`rotate(-90 10 ${H / 2})`} textAnchor="middle">
        observed hit rate
      </text>
    </svg>
  );
}

export default function CalibrationCard() {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    let alive = true;
    getCalibration()
      .then((d) => alive && setData(d))
      .catch((e) => alive && setErr(e));
    return () => {
      alive = false;
    };
  }, []);

  if (err) return null; // calibration is a nice-to-have; never block the report
  if (!data) return null;

  const { n_resolved, n_pending, brier, reliability, per_agent, fit } = data;

  if (!n_resolved) {
    return (
      <p className="calibration-coldstart">
        Confidence is not yet calibrated against outcomes
        {n_pending ? ` — ${n_pending} prediction${n_pending === 1 ? "" : "s"} maturing` : ""}.
        Using hand-tuned defaults.
      </p>
    );
  }

  return (
    <div className="calibration-card">
      <div className="calibration-head">
        <strong>Confidence calibration</strong>
        <span className="calibration-meta">
          {fit
            ? `fitted on ${fit.n_samples} outcomes${fit.through_date ? ` through ${fit.through_date}` : ""}`
            : `${n_resolved} resolved (cold-start defaults)`}
          {brier != null && ` · Brier ${brier.toFixed(3)}`}
        </span>
      </div>
      <ReliabilityCurve points={reliability} />
      {per_agent.length > 0 && (
        <ul className="calibration-agents">
          {per_agent.map((a) => (
            <li key={a.agent} className="calibration-agent-row">
              <span className="calibration-agent">
                {AGENT_LABELS[a.agent] || a.agent}
              </span>
              <span className="calibration-agent-stat">
                stated {Math.round(a.mean_confidence * 100)}% · right{" "}
                {Math.round(a.hit_rate * 100)}% <em>(n={a.count})</em>
              </span>
            </li>
          ))}
        </ul>
      )}
      <p className="calibration-caveat">
        Backtested on a small, self-selected sample vs {data.benchmark} over{" "}
        {data.horizon_days} trading days — indicative, not predictive.
      </p>
    </div>
  );
}
