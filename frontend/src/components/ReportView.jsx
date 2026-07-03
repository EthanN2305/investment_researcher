import ClaimCard from "./ClaimCard.jsx";
import { AGENT_LABELS } from "./AgentProgress.jsx";

const FLAG_LABELS = {
  missing_news: "News source unavailable",
  no_recent_news: "No recent news found",
  no_claims_from_news: "News produced no claims",
  news_unavailable: "News agent failed — report excludes news",
  financials_unavailable: "SEC financials unavailable",
  technicals_unavailable: "Technical analysis unavailable",
  valuation_unavailable: "Valuation unavailable",
  valuation_without_financials: "Valuation computed without SEC financials",
  missing_debt_data: "Debt figures missing from filings",
  missing_revenue: "Revenue missing from filings",
  insufficient_history_for_sma200: "Not enough history for 200-day average",
  recommendation_llm_failed: "Synthesis unavailable — showing raw claims",
  no_claims_to_synthesize: "No claims available to synthesize",
};

function StanceBadge({ stance, confidence }) {
  const pct = Math.round((confidence ?? 0) * 100);
  return (
    <span className={`stance ${stance}`}>
      {stance} · {pct}%
    </span>
  );
}

export default function ReportView({ report }) {
  const {
    ticker, depth, lens, agent_reports = [], recommendation,
    flags = [], generated_at, disclaimer,
  } = report;

  return (
    <section className="report">
      <div className="report-head">
        <h2>{ticker}</h2>
        <span className="report-meta">
          {depth === "quick" ? "Quick check" : "Deep dive"}
          {lens ? ` · ${lens} lens` : ""}
        </span>
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

      {recommendation && (
        <div className="summary recommendation">
          <h3>
            Recommendation{" "}
            <StanceBadge
              stance={recommendation.stance}
              confidence={recommendation.confidence}
            />
          </h3>
          <p>{recommendation.summary}</p>
        </div>
      )}

      {agent_reports.map((ar) => (
        <div key={ar.agent} className="agent-section">
          <h3>
            {AGENT_LABELS[ar.agent] || ar.agent}
            {ar.status === "failed" && (
              <span className="agent-failed"> — unavailable</span>
            )}
          </h3>
          {ar.claims.length === 0 ? (
            <p className="empty">
              {ar.status === "failed"
                ? "This agent failed; its data is missing from the report."
                : "No claims from this agent."}
            </p>
          ) : (
            <ul className="claims">
              {ar.claims.map((c, i) => (
                <ClaimCard key={i} claim={c} />
              ))}
            </ul>
          )}
        </div>
      ))}

      {disclaimer && <p className="disclaimer">{disclaimer}</p>}
    </section>
  );
}
