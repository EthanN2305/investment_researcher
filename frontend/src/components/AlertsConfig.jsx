import { useEffect, useState } from "react";
import { deleteAlertRule, getAlertRules, saveAlertRule } from "../api.js";

const CONDITIONS = [
  {
    value: "price_move",
    label: "Price move",
    hint: "Fires when the 1-day move exceeds the threshold (%).",
    thresholdLabel: "±% move",
    defaultThreshold: 5,
  },
  {
    value: "high_confidence_claim",
    label: "New high-confidence claim",
    hint: "Fires when a new claim appears at or above the confidence threshold.",
    thresholdLabel: "Min confidence (0–1)",
    defaultThreshold: 0.85,
  },
  {
    value: "negative_news",
    label: "Negative news",
    hint: "Fires when a new negative-sounding news claim appears.",
    thresholdLabel: null,
    defaultThreshold: null,
  },
];

const CONDITION_LABELS = Object.fromEntries(
  CONDITIONS.map((c) => [c.value, c.label]),
);

export default function AlertsConfig() {
  const [rules, setRules] = useState(null); // null = loading
  const [ticker, setTicker] = useState("");
  const [condition, setCondition] = useState("price_move");
  const [threshold, setThreshold] = useState("5");
  const [email, setEmail] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    getAlertRules().then(setRules).catch((e) => setError(e.message));
  }, []);

  const meta = CONDITIONS.find((c) => c.value === condition);

  function onConditionChange(value) {
    setCondition(value);
    const m = CONDITIONS.find((c) => c.value === value);
    setThreshold(m?.defaultThreshold != null ? String(m.defaultThreshold) : "");
  }

  async function onAdd(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await saveAlertRule({
        ticker: ticker.trim().toUpperCase(),
        condition,
        threshold:
          meta?.thresholdLabel && threshold !== "" ? Number(threshold) : null,
        email,
        active: true,
      });
      setRules(await getAlertRules());
      setTicker("");
    } catch (err) {
      setError(err.message || "Could not save the alert.");
    } finally {
      setBusy(false);
    }
  }

  async function onToggleActive(rule) {
    setError("");
    try {
      await saveAlertRule({ ...rule, active: !rule.active });
      setRules(await getAlertRules());
    } catch (err) {
      setError(err.message || "Could not update the alert.");
    }
  }

  async function onDelete(id) {
    setError("");
    try {
      await deleteAlertRule(id);
      setRules((rs) => rs.filter((r) => r.id !== id));
    } catch (err) {
      setError(err.message || "Could not delete the alert.");
    }
  }

  return (
    <section className="panel">
      <h3>Alerts</h3>
      <p className="panel-note">
        Checked during each daily (or manual) summary run. Notifications appear
        in the bell; email is optional per rule.
      </p>
      <form className="alert-form" onSubmit={onAdd}>
        <input
          aria-label="Ticker"
          placeholder="Ticker"
          value={ticker}
          onChange={(e) => setTicker(e.target.value)}
          maxLength={12}
          required
        />
        <select
          aria-label="Condition"
          value={condition}
          onChange={(e) => onConditionChange(e.target.value)}
        >
          {CONDITIONS.map((c) => (
            <option key={c.value} value={c.value}>
              {c.label}
            </option>
          ))}
        </select>
        {meta?.thresholdLabel && (
          <input
            aria-label={meta.thresholdLabel}
            type="number"
            placeholder={meta.thresholdLabel}
            step="any"
            min="0"
            value={threshold}
            onChange={(e) => setThreshold(e.target.value)}
          />
        )}
        <label className="email-toggle">
          <input
            type="checkbox"
            checked={email}
            onChange={(e) => setEmail(e.target.checked)}
          />
          Email
        </label>
        <button type="submit" disabled={busy || !ticker.trim()}>
          {busy ? "…" : "Add alert"}
        </button>
      </form>
      {meta && <p className="panel-note condition-hint">{meta.hint}</p>}
      {error && <p className="auth-error" role="alert">{error}</p>}

      {rules === null ? (
        <p className="empty">Loading alerts…</p>
      ) : rules.length === 0 ? (
        <p className="empty">No alerts configured yet.</p>
      ) : (
        <table className="holdings-table">
          <thead>
            <tr>
              <th>Ticker</th><th>Condition</th><th>Threshold</th>
              <th>Email</th><th>Active</th><th></th>
            </tr>
          </thead>
          <tbody>
            {rules.map((r) => (
              <tr key={r.id} className={r.active ? "" : "rule-inactive"}>
                <td className="ticker-cell">{r.ticker}</td>
                <td>{CONDITION_LABELS[r.condition] || r.condition}</td>
                <td>{r.threshold ?? "default"}</td>
                <td>{r.email ? "✓" : "—"}</td>
                <td>
                  <button
                    type="button"
                    className="linklike"
                    onClick={() => onToggleActive(r)}
                  >
                    {r.active ? "On" : "Off"}
                  </button>
                </td>
                <td>
                  <button
                    type="button"
                    className="remove-btn"
                    aria-label={`Delete alert on ${r.ticker}`}
                    onClick={() => onDelete(r.id)}
                  >
                    ✕
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
