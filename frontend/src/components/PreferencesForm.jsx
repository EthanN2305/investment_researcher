import { useEffect, useState } from "react";
import { getPreferences, savePreferences } from "../api.js";

const SECTORS = [
  "Technology", "Healthcare", "Financial Services", "Energy",
  "Consumer Cyclical", "Consumer Defensive", "Industrials",
  "Communication Services", "Utilities", "Real Estate", "Basic Materials",
];

// Stated preferences: risk tolerance, sector interests, lean, horizon.
export default function PreferencesForm() {
  const [prefs, setPrefs] = useState(null); // null = loading
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    getPreferences().then(setPrefs).catch((e) => setError(e.message));
  }, []);

  function update(field, value) {
    setSaved(false);
    setPrefs((p) => ({ ...p, [field]: value }));
  }

  function toggleSector(sector) {
    setSaved(false);
    setPrefs((p) => {
      const has = p.sector_interests.includes(sector);
      return {
        ...p,
        sector_interests: has
          ? p.sector_interests.filter((s) => s !== sector)
          : [...p.sector_interests, sector],
      };
    });
  }

  async function onSave(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      setPrefs(await savePreferences(prefs));
      setSaved(true);
    } catch (err) {
      setError(err.message || "Could not save preferences.");
    } finally {
      setBusy(false);
    }
  }

  if (prefs === null) {
    return (
      <section className="panel">
        <h3>My preferences</h3>
        <p className="empty">{error || "Loading preferences…"}</p>
      </section>
    );
  }

  return (
    <section className="panel">
      <h3>My preferences</h3>
      <form className="prefs-form" onSubmit={onSave}>
        <label>
          Risk tolerance
          <select
            value={prefs.risk_tolerance || ""}
            onChange={(e) => update("risk_tolerance", e.target.value || null)}
          >
            <option value="">Not set</option>
            <option value="low">Low</option>
            <option value="medium">Medium</option>
            <option value="high">High</option>
          </select>
        </label>

        <label>
          Growth vs value lean
          <select
            value={prefs.growth_value_lean || ""}
            onChange={(e) => update("growth_value_lean", e.target.value || null)}
          >
            <option value="">Not set</option>
            <option value="growth">Growth</option>
            <option value="value">Value</option>
            <option value="balanced">Balanced</option>
          </select>
        </label>

        <label>
          Time horizon
          <select
            value={prefs.time_horizon || ""}
            onChange={(e) => update("time_horizon", e.target.value || null)}
          >
            <option value="">Not set</option>
            <option value="short">Short (&lt; 2 years)</option>
            <option value="medium">Medium (2–10 years)</option>
            <option value="long">Long (10+ years)</option>
          </select>
        </label>

        <fieldset className="sector-picker">
          <legend>Sector interests</legend>
          <div className="sector-chips">
            {SECTORS.map((s) => (
              <button
                key={s}
                type="button"
                className={`chip ${prefs.sector_interests.includes(s) ? "on" : ""}`}
                onClick={() => toggleSector(s)}
              >
                {s}
              </button>
            ))}
          </div>
        </fieldset>

        <div className="prefs-actions">
          <button type="submit" disabled={busy}>
            {busy ? "Saving…" : "Save preferences"}
          </button>
          {saved && <span className="saved-note">Saved ✓</span>}
        </div>
        {error && <p className="auth-error" role="alert">{error}</p>}
      </form>
    </section>
  );
}
