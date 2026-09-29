import { useState, type FormEvent } from "react";
import { useAuth } from "../auth/AuthProvider";

export function Setup() {
  const { completeSetup, error } = useAuth();
  const [organizationName, setOrganizationName] = useState("");
  const [companyName, setCompanyName] = useState("");
  const [adminName, setAdminName] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [localError, setLocalError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setLocalError(null);

    if (password.length < 8) {
      setLocalError("Password must be at least 8 characters.");
      return;
    }
    if (password !== confirmPassword) {
      setLocalError("Passwords don't match.");
      return;
    }

    setSubmitting(true);
    try {
      await completeSetup({
        organization_name: organizationName,
        company_name: companyName,
        admin_name: adminName,
        username,
        password,
      });
    } catch {
      // error surfaced via auth context
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="login-shell">
      <form className="login-card" style={{ maxWidth: 420 }} onSubmit={handleSubmit}>
        <span className="brand" style={{ color: "var(--ink)", marginBottom: 4 }}>
          <span className="mark">A</span> Albiruni <span style={{ opacity: 0.55, fontWeight: 400 }}>ERP</span>
        </span>
        <p className="login-sub">
          No organization set up yet. Create your organization and the first Super Admin account to get started.
        </p>

        <label className="login-field">
          <span>Organization name</span>
          <input
            id="setup-org"
            value={organizationName}
            onChange={(e) => setOrganizationName(e.target.value)}
            placeholder="Albiruni Trading Group"
            autoFocus
            required
          />
        </label>
        <label className="login-field">
          <span>First company / branch</span>
          <input
            id="setup-company"
            value={companyName}
            onChange={(e) => setCompanyName(e.target.value)}
            placeholder="Kozhikode HQ"
            required
          />
        </label>
        <label className="login-field">
          <span>Your name</span>
          <input id="setup-admin-name" value={adminName} onChange={(e) => setAdminName(e.target.value)} required />
        </label>
        <label className="login-field">
          <span>Admin username</span>
          <input
            id="setup-username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="username"
            required
          />
        </label>
        <label className="login-field">
          <span>Password</span>
          <input
            id="setup-password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="new-password"
            required
          />
        </label>
        <label className="login-field">
          <span>Confirm password</span>
          <input
            id="setup-password-confirm"
            type="password"
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            autoComplete="new-password"
            required
          />
        </label>

        {(localError || error) && <div className="login-error">{localError ?? error}</div>}

        <button className="primary-btn login-submit" type="submit" disabled={submitting}>
          {submitting ? "Creating…" : "Create organization & Super Admin"}
        </button>

        <p className="login-hint">
          This account gets every permission (<code>*</code>) — the Super Admin role. Create day-to-day users with
          narrower roles afterward.
        </p>
      </form>
    </div>
  );
}
