import { useState } from "react";
import { fetchResearch } from "./api.js";
import ReportView from "./components/ReportView.jsx";

export default function App() {
  const [ticker, setTicker] = useState("");
  const [status, setStatus] = useState("idle"); // idle | loading | done | error
  const [report, setReport] = useState(null);
  const [error, setError] = useState("");

  async function onSubmit(e) {
    e.preventDefault();
    const symbol = ticker.trim().toUpperCase();
    if (!symbol) return;

    setStatus("loading");
    setError("");
    setReport(null);
    try {
      const data = await fetchResearch(symbol);
      setReport(data);
      setStatus("done");
    } catch (err) {
      setError(err.message || "Something went wrong.");
      setStatus("error");
    }
  }

  return (
    <div className="app">
      <header className="header">
        <h1>AI Investment Research Analyst</h1>
        <p className="tagline">
          Enter a ticker for a sourced, confidence-scored research report.
        </p>
      </header>

      <form className="search" onSubmit={onSubmit}>
        <input
          aria-label="Stock ticker"
          placeholder="e.g. AAPL"
          value={ticker}
          onChange={(e) => setTicker(e.target.value)}
          maxLength={12}
          autoFocus
        />
        <button type="submit" disabled={status === "loading" || !ticker.trim()}>
          {status === "loading" ? "Researching…" : "Research"}
        </button>
      </form>

      {status === "loading" && (
        <div className="loading">
          <div className="spinner" aria-hidden="true" />
          <span>Fetching market data and news, then reasoning over it…</span>
        </div>
      )}

      {status === "error" && (
        <div className="error" role="alert">
          <strong>Could not generate report.</strong>
          <p>{error}</p>
        </div>
      )}

      {status === "done" && report && <ReportView report={report} />}

      <footer className="footer">
        Informational research only — not investment advice.
      </footer>
    </div>
  );
}
