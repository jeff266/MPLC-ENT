import { useState } from "react";
import { login, signup, setToken } from "../api/client";

/** Gate screen shown by App.tsx when there's no valid token. Added
 * 2026-11-14 alongside the backend's whole-app auth middleware. Simple
 * email+password, multi-user sign-up (Jeff's choice over one fixed admin
 * account, AskUserQuestion 2026-11-14) -- no password-reset flow yet,
 * since there's no email-sending set up in this app to send a reset
 * link through; if an account's password is lost today, it needs a
 * direct DB fix (delete the row, sign up again) until that's built. */
export function Login({ onAuthenticated }: { onAuthenticated: () => void }) {
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const { access_token } = mode === "login" ? await login(email, password) : await signup(email, password);
      setToken(access_token);
      onAuthenticated();
    } catch (err) {
      setError(String((err as Error)?.message ?? err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="login-screen">
      <form className="login-form" onSubmit={handleSubmit}>
        <h1>PoP Detection Engine</h1>
        <div className="login-tabs">
          <button
            type="button"
            className={mode === "login" ? "tab-active" : ""}
            onClick={() => {
              setMode("login");
              setError(null);
            }}
          >
            Log in
          </button>
          <button
            type="button"
            className={mode === "signup" ? "tab-active" : ""}
            onClick={() => {
              setMode("signup");
              setError(null);
            }}
          >
            Sign up
          </button>
        </div>

        <label>
          Email
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            autoFocus
          />
        </label>
        <label>
          Password
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            minLength={mode === "signup" ? 8 : undefined}
          />
        </label>

        {error && <p className="action-error">{error}</p>}

        <button type="submit" className="primary" disabled={submitting}>
          {submitting ? "…" : mode === "login" ? "Log in" : "Create account"}
        </button>
      </form>
    </div>
  );
}
