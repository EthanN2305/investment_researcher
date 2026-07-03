export const AGENT_LABELS = {
  planner: "Planner",
  news: "News",
  financials: "Financial Statements",
  technicals: "Technical Analysis",
  valuation: "Valuation",
  recommendation: "Recommendation",
};

const STATE_ICONS = { pending: "○", started: "◐", done: "●", failed: "✕" };

export default function AgentProgress({ agents }) {
  const entries = Object.entries(agents);
  if (entries.length === 0) return null;

  return (
    <div className="agents-progress" role="status" aria-label="Agent progress">
      {entries.map(([id, info]) => (
        <div key={id} className={`agent-row ${info.state}`}>
          <span className="agent-state" aria-hidden="true">
            {STATE_ICONS[info.state] || "○"}
          </span>
          <span className="agent-name">{AGENT_LABELS[id] || id}</span>
          <span className="agent-message">{info.message || ""}</span>
        </div>
      ))}
    </div>
  );
}
