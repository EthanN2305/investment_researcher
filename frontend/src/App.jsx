import { useEffect, useRef, useState } from "react";
import { answerQuestion, startResearch, subscribeToRun } from "./api.js";
import AgentProgress from "./components/AgentProgress.jsx";
import QuestionCard from "./components/QuestionCard.jsx";
import ReportView from "./components/ReportView.jsx";

export default function App() {
  const [ticker, setTicker] = useState("");
  const [depth, setDepth] = useState("deep"); // "quick" | "deep" | "" (planner asks)
  const [status, setStatus] = useState("idle"); // idle | running | question | done | error
  const [agents, setAgents] = useState({});
  const [question, setQuestion] = useState(null);
  const [answering, setAnswering] = useState(false);
  const [report, setReport] = useState(null);
  const [error, setError] = useState("");
  const runIdRef = useRef(null);
  const closeRef = useRef(null);

  useEffect(() => () => closeRef.current?.(), []);

  function handleEvent(event) {
    switch (event.type) {
      case "plan":
        // Planner chose the agents — seed the progress board.
        setAgents((prev) => {
          const next = {};
          for (const id of event.agents) {
            next[id] = prev[id] || { state: "pending", message: "" };
          }
          return next;
        });
        break;
      case "status":
        setAgents((prev) => ({
          ...prev,
          [event.agent]: { state: event.state, message: event.message || "" },
        }));
        break;
      case "question":
        setQuestion({ question: event.question, options: event.options || [] });
        setStatus("question");
        break;
      case "report":
        setReport(event.report);
        break;
      case "done":
        setStatus("done");
        break;
      case "error":
        setError(event.message || "The run failed.");
        setStatus("error");
        break;
      default:
        break;
    }
  }

  async function onSubmit(e) {
    e.preventDefault();
    const symbol = ticker.trim().toUpperCase();
    if (!symbol) return;

    closeRef.current?.();
    setStatus("running");
    setError("");
    setReport(null);
    setQuestion(null);
    setAgents({ planner: { state: "started", message: "Planning…" } });

    try {
      const { run_id } = await startResearch(symbol, { depth });
      runIdRef.current = run_id;
      closeRef.current = subscribeToRun(run_id, handleEvent, (err) => {
        setError(err.message);
        setStatus("error");
      });
    } catch (err) {
      setError(err.message || "Something went wrong.");
      setStatus("error");
    }
  }

  async function onAnswer(answer) {
    setAnswering(true);
    try {
      await answerQuestion(runIdRef.current, answer);
      setQuestion(null);
      setStatus("running");
    } catch (err) {
      setError(err.message || "Could not send the answer.");
      setStatus("error");
    } finally {
      setAnswering(false);
    }
  }

  const busy = status === "running" || status === "question";

  return (
    <div className="app">
      <header className="header">
        <h1>AI Investment Research Analyst</h1>
        <p className="tagline">
          A planner coordinates news, SEC financials, valuation, and technical
          agents — then synthesizes a sourced, confidence-scored report.
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
        <select
          aria-label="Research depth"
          value={depth}
          onChange={(e) => setDepth(e.target.value)}
        >
          <option value="deep">Deep dive</option>
          <option value="quick">Quick check</option>
          <option value="">Let the planner ask</option>
        </select>
        <button type="submit" disabled={busy || !ticker.trim()}>
          {busy ? "Researching…" : "Research"}
        </button>
      </form>

      {busy && <AgentProgress agents={agents} />}

      {status === "question" && question && (
        <QuestionCard
          question={question.question}
          options={question.options}
          onAnswer={onAnswer}
          busy={answering}
        />
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
