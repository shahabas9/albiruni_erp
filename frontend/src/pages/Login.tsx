import { BrandMark } from "../components/Icon";
import { useState, type FormEvent } from "react";
import { useAuth } from "../auth/AuthProvider";

export function Login() {
  const { login, error } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    try {
      await login(username, password);
    } catch {
      // error surfaced via auth context
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="login-shell">
      <form className="login-card" onSubmit={handleSubmit}>
        <span className="brand" style={{ color: "var(--ink)", marginBottom: 4 }}>
          <BrandMark /> Albiruni <span style={{ opacity: 0.55, fontWeight: 600 }}>ERP</span>
        </span>
        <p className="login-sub">Sign in to run the business by asking.</p>

        <label className="login-field">
          <span>Username</span>
          <input
            id="login-username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="username"
            autoFocus
          />
        </label>
        <label className="login-field">
          <span>Password</span>
          <input
            id="login-password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
          />
        </label>

        {error && <div className="login-error">{error}</div>}

        <button className="primary-btn login-submit" type="submit" disabled={submitting}>
          {submitting ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </div>
  );
}
