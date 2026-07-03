function confidenceLabel(c) {
  if (c >= 0.75) return "high";
  if (c >= 0.5) return "medium";
  return "low";
}

function isUrl(s) {
  return typeof s === "string" && /^https?:\/\//i.test(s);
}

export default function ClaimCard({ claim }) {
  const pct = Math.round((claim.confidence ?? 0) * 100);
  const level = confidenceLabel(claim.confidence ?? 0);

  return (
    <li className="claim-card">
      <div className="claim-head">
        <p className="claim-text">{claim.claim}</p>
        <span className={`confidence ${level}`} title="Model confidence">
          {pct}%
        </span>
      </div>
      <p className="claim-evidence">{claim.evidence}</p>
      <p className="claim-source">
        Source:{" "}
        {isUrl(claim.source) ? (
          <a href={claim.source} target="_blank" rel="noopener noreferrer">
            {claim.source}
          </a>
        ) : (
          <span>{claim.source}</span>
        )}
      </p>
    </li>
  );
}
