import { useEffect, useRef, useState } from "react";
import {
  answerQuestion,
  clearAuth,
  getAuth,
  startResearch,
  subscribeToRun,
} from "./api.js";
import AgentProgress from "./components/AgentProgress.jsx";
import AlertsConfig from "./components/AlertsConfig.jsx";
import AuthForm from "./components/AuthForm.jsx";
import DigestSettings from "./components/DigestSettings.jsx";
import LearnPanel from "./components/LearnPanel.jsx";
import NotificationBell from "./components/NotificationBell.jsx";
import PortfolioDashboard from "./components/PortfolioDashboard.jsx";
import PortfolioPanel from "./components/PortfolioPanel.jsx";
import PreferencesForm from "./components/PreferencesForm.jsx";
import QuestionCard from "./components/QuestionCard.jsx";
import RecommendationsPanel from "./components/RecommendationsPanel.jsx";
import ReportView from "./components/ReportView.jsx";
import SummaryFeed from "./components/SummaryFeed.jsx";
import WatchlistPanel from "./components/WatchlistPanel.jsx";

// Views: research | feed | watchlist | alerts | portfolio
const TABS = [
  ["research", "Research"],
  ["recommendations", "Recommendations"],
  ["learn", "Learn"],
  ["feed", "Daily Feed"],
  ["watchlist", "Watchlist"],
  ["alerts", "Alerts"],
  ["portfolio", "My Portfolio"],
];

export default function App() {
  const [view, setView] = useState("research");
  const [user, setUser] = useState(() => getAuth()); // {token, email} | null
  const [holdingsVersion, setHoldingsVersion] = useState(0); // bump → dashboard refetch

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
    startRun(ticker.trim().toUpperCase());
  }

  // Also reachable from the watchlist's "Research now" buttons.
  async function startRun(symbol) {
    if (!symbol) return;
    setTicker(symbol);
    setView("research");

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

  // Landing-style fixed nav: add glass blur once the page scrolls.
  const [scrolled, setScrolled] = useState(false);
  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <div className="app">
      <div className="bg-atmosphere" aria-hidden="true"></div>
      <div className="bg-grid" aria-hidden="true"></div>

      <header className={scrolled ? "nav scrolled" : "nav"}>
        <div className="container nav-inner">
          <div className="brand">
            <span className="brand-mark" aria-hidden="true">
              <svg viewBox="0 0 24 24">
                <path d="M4 16l4-7 4 4 4-8 4 6" />
              </svg>
            </span>
            MarketPilot
          </div>
          <nav className="nav-links" aria-label="Views">
            {TABS.map(([id, label]) => (
              <button
                key={id}
                type="button"
                className={view === id ? "nav-link on" : "nav-link"}
                onClick={() => setView(id)}
              >
                {label}
              </button>
            ))}
          </nav>
          <div className="auth-status">
            {user ? (
              <>
                <NotificationBell />
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
        <nav className="tabs-mobile" aria-label="Views">
          {TABS.map(([id, label]) => (
            <button
              key={id}
              type="button"
              className={view === id ? "tab on" : "tab"}
              onClick={() => setView(id)}
            >
              {label}
            </button>
          ))}
        </nav>
      </header>

      <main className="container page">
        <div className="page-head">
          <h1>
            AI-powered <span className="grad">investment research</span>
          </h1>
          <p className="tagline">
            A planner coordinates news, SEC financials, valuation, and
            technical agents — then synthesizes a sourced, confidence-scored
            report{user ? ", personalized to your portfolio." : "."}
          </p>
        </div>

        {view !== "research" && !user ? (
        <AuthForm
          onAuthed={() => {
            setUser(getAuth());
          }}
        />
      ) : view === "portfolio" ? (
        <>
          <PortfolioDashboard refreshKey={holdingsVersion} />
          <PortfolioPanel
            onChange={() => setHoldingsVersion((v) => v + 1)}
          />
          <PreferencesForm />
        </>
      ) : view === "recommendations" ? (
        <RecommendationsPanel onResearch={startRun} />
      ) : view === "learn" ? (
        <LearnPanel />
      ) : view === "watchlist" ? (
        <WatchlistPanel onResearch={startRun} />
      ) : view === "feed" ? (
        <>
          <SummaryFeed />
          <DigestSettings />
        </>
      ) : view === "alerts" ? (
        <AlertsConfig />
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
      </main>

      <footer className="footer">
        <div className="container footer-inner">
          <div className="brand brand-sm">
            <span className="brand-mark" aria-hidden="true">
              <svg viewBox="0 0 24 24">
                <path d="M4 16l4-7 4 4 4-8 4 6" />
              </svg>
            </span>
            MarketPilot
          </div>
          <p>Informational research only — not investment advice.</p>
        </div>
      </footer>
    </div>
  );
}
