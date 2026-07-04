import { useEffect, useState } from "react";
import { getDigestPrefs, saveDigestPrefs, sendDigestNow } from "../api.js";

const FREQUENCIES = [
  { value: "daily", label: "Every day" },
  { value: "weekly", label: "Every week" },
  { value: "monthly", label: "Start of every month" },
];

const WEEKDAYS = [
  "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
];

function describe(enabled, frequency, weekday) {
  if (!enabled) return "Digest emails are off.";
  if (frequency === "daily") {
    return "You'll get your feed by email every day, right after the daily run.";
  }
  if (frequency === "weekly") {
    return `You'll get your feed by email every ${WEEKDAYS[weekday ?? 0]}.`;
  }
  return "You'll get your feed by email on the 1st of every month.";
}

// Email digest settings: choose how often the daily feed lands in your inbox.
export default function DigestSettings() {
  const [enabled, setEnabled] = useState(false);
  const [frequency, setFrequency] = useState("daily");
  const [weekday, setWeekday] = useState(0);
  const [lastSent, setLastSent] = useState(null);
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [sending, setSending] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    getDigestPrefs()
      .then((p) => {
        setEnabled(p.enabled);
        setFrequency(p.frequency || "daily");
        setWeekday(p.weekday ?? 0);
        setLastSent(p.last_sent_at);
        setLoaded(true);
      })
      .catch((e) => setError(e.message));
  }, []);

  async function onSave(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const saved = await saveDigestPrefs({
        enabled,
        frequency,
        weekday: frequency === "weekly" ? Number(weekday) : null,
      });
      setLastSent(saved.last_sent_at);
      setMessage("Saved. " + describe(saved.enabled, saved.frequency, saved.weekday));
    } catch (err) {
      setError(err.message || "Could not save digest settings.");
    } finally {
      setBusy(false);
    }
  }

  async function onSendNow() {
    setSending(true);
    setError("");
    setMessage("");
    try {
      await sendDigestNow();
      setMessage(
        "Digest sent — check your inbox (in dev without SMTP configured, " +
        "it's printed to the backend console).",
      );
    } catch (err) {
      setError(err.message || "Could not send the digest.");
    } finally {
      setSending(false);
    }
  }

  return (
    <section className="panel">
      <h3>Email digest</h3>
      <p className="panel-note">
        Get your daily feed delivered by email on a schedule you choose. Sent
        automatically after the daily summary run.
      </p>

      {!loaded && !error ? (
        <p className="empty">Loading settings…</p>
      ) : (
        <form className="digest-form" onSubmit={onSave}>
          <label className="email-toggle">
            <input
              type="checkbox"
              checked={enabled}
              onChange={(e) => setEnabled(e.target.checked)}
            />
            Email me my feed
          </label>

          <select
            aria-label="Frequency"
            value={frequency}
            onChange={(e) => setFrequency(e.target.value)}
            disabled={!enabled}
          >
            {FREQUENCIES.map((f) => (
              <option key={f.value} value={f.value}>
                {f.label}
              </option>
            ))}
          </select>

          {frequency === "weekly" && (
            <select
              aria-label="Day of week"
              value={weekday}
              onChange={(e) => setWeekday(e.target.value)}
              disabled={!enabled}
            >
              {WEEKDAYS.map((d, i) => (
                <option key={d} value={i}>
                  on {d}
                </option>
              ))}
            </select>
          )}

          <button type="submit" disabled={busy}>
            {busy ? "…" : "Save"}
          </button>
          <button
            type="button"
            className="secondary"
            onClick={onSendNow}
            disabled={sending}
          >
            {sending ? "Sending…" : "Send test email"}
          </button>
        </form>
      )}

      {loaded && (
        <p className="panel-note digest-status">
          {describe(enabled, frequency, Number(weekday))}
          {lastSent &&
            ` Last sent ${new Date(lastSent).toLocaleString()}.`}
        </p>
      )}
      {message && <p className="digest-ok" role="status">{message}</p>}
      {error && <p className="auth-error" role="alert">{error}</p>}
    </section>
  );
}
