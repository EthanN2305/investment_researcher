import { useState } from "react";
import { login, signup } from "../api.js";

// Sign-in / create-account form. Calls onAuthed(email) on success.
export default function AuthForm({ onAuthed }) {
  const [mode, setMode] = useState("login"); // "login" | "signup"
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function onSubmit(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const fn = mode === "login" ? login : signup;
      const data = await fn(email.trim(), password);
      onAuthed(data.email);
    } catch (err) {
      setError(err.message || "Authentication failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth-card">
      <h3>{mode === "login" ? "Sign in" : "Create account"}</h3>
      <p className="auth-blurb">
        Store your portfolio and preferences to get research personalized to
        your actual holdings.
      </p>
      <form className="auth-form" onSubmit={onSubmit}>
        <input
          type="email"
          placeholder="Email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          autoComplete="email"
          required
        />
        <input
          type="password"
          placeholder={mode === "signup" ? "Password (8+ characters)" : "Password"}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoComplete={mode === "login" ? "current-password" : "new-password"}
          minLength={mode === "signup" ? 8 : undefined}
          required
        />
        <button type="submit" disabled={busy}>
          {busy ? "…" : mode === "login" ? "Sign in" : "Sign up"}
        </button>
      </form>
      {error && <p className="auth-error" role="alert">{error}</p>}
      <button
        type="button"
        className="auth-switch"
        onClick={() => { setMode(mode === "login" ? "signup" : "login"); setError(""); }}
      >
        {mode === "login"
          ? "New here? Create an account"
          : "Already have an account? Sign in"}
      </button>
    </div>
  );
}
