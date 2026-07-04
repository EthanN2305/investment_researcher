import { useState } from "react";

// Phase 4: claims are collapsed by default — headline + visual confidence
// indicator — and expand to reveal the evidence and source behind them.

export function confidenceLabel(c) {
  if (c >= 0.75) return "high";
  if (c >= 0.5) return "medium";
  return "low";
}

export function ConfidenceBar({ value, compact = false }) {
  const pct = Math.round((value ?? 0) * 100);
  const level = confidenceLabel(value ?? 0);
  return (
    <span
      className={`conf-indicator ${level} ${compact ? "compact" : ""}`}
      title={`Confidence: ${pct}%`}
    >
      <span className="conf-track" aria-hidden="true">
        <span className="conf-fill" style={{ width: `${pct}%` }} />
      </span>
      <span className="conf-pct">{pct}%</span>
    </span>
  );
}

function isUrl(s) {
  return typeof s === "string" && /^https?:\/\//i.test(s);
}

export default function ClaimCard({ claim, defaultOpen = false }) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <li className={`claim-card ${open ? "open" : ""}`}>
      <button
        type="button"
        className="claim-head expandable"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
      >
        <span className="claim-chevron" aria-hidden="true">
          {open ? "▾" : "▸"}
        </span>
        <p className="claim-text">{claim.claim}</p>
        <ConfidenceBar value={claim.confidence} compact />
      </button>
      {open && (
        <div className="claim-details">
          <p className="claim-evidence">
            <span className="detail-label">Evidence</span>
            {claim.evidence}
          </p>
          <p className="claim-source">
            <span className="detail-label">Source</span>
            {isUrl(claim.source) ? (
              <a href={claim.source} target="_blank" rel="noopener noreferrer">
                {claim.source}
              </a>
            ) : (
              <span>{claim.source}</span>
            )}
          </p>
        </div>
      )}
    </li>
  );
}
