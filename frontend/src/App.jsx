import { useEffect, useRef, useState } from "react";
import {
  answerQuestion,
  clearAuth,
  getAuth,
  startResearch,
  subscribeToRun,
} from "./api.js";
import AgentProgress from "./components/AgentProgress.jsx";
import AuthForm from "./components/AuthForm.jsx";
import PortfolioPanel from "./components/PortfolioPanel.jsx";
import PreferencesForm from "./components/PreferencesForm.jsx";
import QuestionCard from "./components/QuestionCard.jsx";
import ReportView from "./components/ReportView.jsx";

export default function App() {
  const [view, setView] = useState("research"); // "research" | "portfolio"
  const [user, setUser] = useState(() => getAuth()); // {token, email} | null

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

  function signOut() {
    clearAuth();
    setUser(null);
    setView("research");
  }

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
      // A stale token is cleared inside the API client — reflect that here.
      if (!getAuth()) setUser(null);
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
        <div className="header-top">
          <h1>AI Investment Research Analyst</h1>
          <div className="auth-status">
            {user ? (
              <>
                <span className="auth-email">{user.email}</span>
                <button type="button" className="linklike" onClick={signOut}>
                  Sign out
                </button>
              </>
            ) : (
              <button
                type="button"
                className="linklike"
                onClick={() => setView("portfolio")}
              >
                Sign in
              </button>
            )}
          </div>
        </div>
        <p className="tagline">
          A planner coordinates news, SEC financials, valuation, and technical
          agents — then synthesizes a sourced, confidence-scored report
          {user ? ", personalized to your portfolio." : "."}
        </p>
        <nav className="tabs" aria-label="Views">
          <button
            type="button"
            className={view === "research" ? "tab on" : "tab"}
            onClick={() => setView("research")}
          >
            Research
          </button>
          <button
            type="button"
            className={view === "portfolio" ? "tab on" : "tab"}
            onClick={() => setView("portfolio")}
          >
            My Portfolio
          </button>
        </nav>
      </header>

      {view === "portfolio" ? (
        user ? (
          <>
            <PortfolioPanel />
            <PreferencesForm />
          </>
        ) : (
          <AuthForm
            onAuthed={() => {
              setUser(getAuth());
              setView("portfolio");
            }}
          />
        )
      ) : (
        <>
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

          {user && status === "idle" && (
            <p className="personalize-note">
              Signed in — reports will include a "how this fits your portfolio"
              section based on your holdings and preferences.
            </p>
          )}

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
        </>
      )}

      <footer className="footer">
        Informational research only — not investment advice.
      </footer>
    </div>
  );
}
