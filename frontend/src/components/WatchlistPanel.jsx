import { useEffect, useState } from "react";
import { addToWatchlist, getWatchlist, removeFromWatchlist } from "../api.js";

// Watchlist: tickers the user tracks but doesn't necessarily own.
// Separate from the portfolio view by design (Phase 4 spec).
export default function WatchlistPanel({ onResearch }) {
  const [items, setItems] = useState(null); // null = loading
  const [ticker, setTicker] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    getWatchlist().then(setItems).catch((e) => setError(e.message));
  }, []);

  async function onAdd(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await addToWatchlist(ticker.trim().toUpperCase(), note.trim());
      setItems(await getWatchlist());
      setTicker("");
      setNote("");
    } catch (err) {
      setError(err.message || "Could not add the ticker.");
    } finally {
      setBusy(false);
    }
  }

  async function onRemove(id) {
    setError("");
    try {
      await removeFromWatchlist(id);
      setItems((xs) => xs.filter((x) => x.id !== id));
    } catch (err) {
      setError(err.message || "Could not remove the ticker.");
    }
  }

  return (
    <section className="panel">
      <h3>My watchlist</h3>
      <p className="panel-note">
        Tickers you're tracking but don't own — the daily summary job covers
        these alongside your holdings.
      </p>
      <form className="holding-form" onSubmit={onAdd}>
        <input
          aria-label="Ticker"
          placeholder="Ticker"
          value={ticker}
          onChange={(e) => setTicker(e.target.value)}
          maxLength={12}
          required
        />
        <input
          aria-label="Note"
          placeholder="Note (optional)"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          maxLength={255}
        />
        <button type="submit" disabled={busy || !ticker.trim()}>
          {busy ? "…" : "Watch"}
        </button>
      </form>
      {error && <p className="auth-error" role="alert">{error}</p>}

      {items === null ? (
        <p className="empty">Loading watchlist…</p>
      ) : items.length === 0 ? (
        <p className="empty">
          Nothing watched yet — add tickers you want daily summaries and
          alerts for.
        </p>
      ) : (
        <ul className="watchlist">
          {items.map((w) => (
            <li key={w.id} className="watchlist-row">
              <span className="ticker-cell">{w.ticker}</span>
              <span className="watchlist-note">{w.note || ""}</span>
              {onResearch && (
                <button
                  type="button"
                  className="linklike"
                  onClick={() => onResearch(w.ticker)}
                >
                  Research now
                </button>
              )}
              <button
                type="button"
                className="remove-btn"
                aria-label={`Remove ${w.ticker}`}
                onClick={() => onRemove(w.id)}
              >
                ✕
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
