import ClaimCard from "./ClaimCard.jsx";

const FLAG_LABELS = {
  missing_news: "News source unavailable",
  no_recent_news: "No recent news found",
  no_claims_generated: "No claims generated",
  no_data: "Data unavailable",
};

export default function ReportView({ report }) {
  const { ticker, summary, claims = [], flags = [], generated_at, disclaimer } =
    report;

  return (
    <section className="report">
      <div className="report-head">
        <h2>{ticker}</h2>
        {generated_at && (
          <span className="timestamp">
            {new Date(generated_at).toLocaleString()}
          </span>
        )}
      </div>

      {flags.length > 0 && (
        <div className="flags" role="status">
          {flags.map((f) => (
            <span key={f} className="flag">
              ⚠ {FLAG_LABELS[f] || f}
            </span>
          ))}
        </div>
      )}

      {summary && (
        <div className="summary">
          <h3>Summary</h3>
          <p>{summary}</p>
        </div>
      )}

      <h3>Claims &amp; evidence</h3>
      {claims.length === 0 ? (
        <p className="empty">No claims were generated for this ticker.</p>
      ) : (
        <ul className="claims">
          {claims.map((c, i) => (
            <ClaimCard key={i} claim={c} />
          ))}
        </ul>
      )}

      {disclaimer && <p className="disclaimer">{disclaimer}</p>}
    </section>
  );
}
