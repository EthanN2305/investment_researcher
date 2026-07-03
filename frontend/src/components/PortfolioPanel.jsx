import { useEffect, useState } from "react";
import { deleteHolding, getHoldings, saveHolding } from "../api.js";

// Holdings editor: list, add/update (POST upserts by ticker), remove.
export default function PortfolioPanel() {
  const [holdings, setHoldings] = useState(null); // null = loading
  const [ticker, setTicker] = useState("");
  const [quantity, setQuantity] = useState("");
  const [costBasis, setCostBasis] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    getHoldings().then(setHoldings).catch((e) => setError(e.message));
  }, []);

  async function onAdd(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await saveHolding({
        ticker: ticker.trim().toUpperCase(),
        quantity: Number(quantity),
        cost_basis: Number(costBasis),
      });
      setHoldings(await getHoldings());
      setTicker("");
      setQuantity("");
      setCostBasis("");
    } catch (err) {
      setError(err.message || "Could not save the holding.");
    } finally {
      setBusy(false);
    }
  }

  async function onDelete(id) {
    setError("");
    try {
      await deleteHolding(id);
      setHoldings((hs) => hs.filter((h) => h.id !== id));
    } catch (err) {
      setError(err.message || "Could not remove the holding.");
    }
  }

  const totalCost = (holdings || []).reduce(
    (sum, h) => sum + h.quantity * h.cost_basis, 0,
  );

  return (
    <section className="panel">
      <h3>My holdings</h3>
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
          aria-label="Quantity"
          type="number"
          placeholder="Shares"
          min="0.0001"
          step="any"
          value={quantity}
          onChange={(e) => setQuantity(e.target.value)}
          required
        />
        <input
          aria-label="Cost basis per share"
          type="number"
          placeholder="Cost basis / share"
          min="0"
          step="any"
          value={costBasis}
          onChange={(e) => setCostBasis(e.target.value)}
          required
        />
        <button type="submit" disabled={busy}>
          {busy ? "…" : "Add / update"}
        </button>
      </form>
      {error && <p className="auth-error" role="alert">{error}</p>}

      {holdings === null ? (
        <p className="empty">Loading holdings…</p>
      ) : holdings.length === 0 ? (
        <p className="empty">
          No holdings yet — add your positions above to unlock personalized
          "how this fits your portfolio" analysis.
        </p>
      ) : (
        <table className="holdings-table">
          <thead>
            <tr>
              <th>Ticker</th><th>Shares</th><th>Cost basis</th>
              <th>Cost value</th><th>Sector</th><th></th>
            </tr>
          </thead>
          <tbody>
            {holdings.map((h) => (
              <tr key={h.id}>
                <td className="ticker-cell">{h.ticker}</td>
                <td>{h.quantity}</td>
                <td>${h.cost_basis.toLocaleString()}</td>
                <td>${(h.quantity * h.cost_basis).toLocaleString()}</td>
                <td className="sector-cell">{h.sector || "—"}</td>
                <td>
                  <button
                    type="button"
                    className="remove-btn"
                    aria-label={`Remove ${h.ticker}`}
                    onClick={() => onDelete(h.id)}
                  >
                    ✕
                  </button>
                </td>
              </tr>
            ))}
            <tr className="total-row">
              <td colSpan={3}>Total (cost value)</td>
              <td>${totalCost.toLocaleString()}</td>
              <td colSpan={2}></td>
            </tr>
          </tbody>
        </table>
      )}
    </section>
  );
}
