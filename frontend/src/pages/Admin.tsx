import { useEffect, useState } from "react";
import {
  ApiError,
  KNOWN_PERMISSIONS,
  createAdminUser,
  createRole,
  fetchAdminUsers,
  fetchRoles,
  updateAdminUser,
  updateRole,
  type AdminUser,
  type Role,
} from "../api/client";
import { useAuth } from "../auth/AuthProvider";

const PERMISSION_HINTS: Record<string, string> = {
  "crm.records.all": "See every lead, deal and follow-up. Without it, people see only the ones they own.",
  "crm.export": "Download CRM lists as CSV (every export is recorded in the audit trail).",
  "crm.settings.write": "Change CRM settings: lead rotation, stale limits, custom fields, targets, web form.",
};

export function Admin() {
  const { user: currentUser } = useAuth();
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [roles, setRoles] = useState<Role[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showUserForm, setShowUserForm] = useState(false);
  const [showRoleForm, setShowRoleForm] = useState(false);
  const [editingUserId, setEditingUserId] = useState<string | null>(null);
  const [editingRoleId, setEditingRoleId] = useState<string | null>(null);

  async function refresh() {
    setLoading(true);
    try {
      const [u, r] = await Promise.all([fetchAdminUsers(), fetchRoles()]);
      setUsers(u);
      setRoles(r);
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't reach the Albiruni API.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  return (
    <section>
      <div className="page-head">
        <div className="eyebrow">Platform</div>
        <h1 className="page-title">Users &amp; Roles</h1>
        <p className="page-sub">Who can sign in, and exactly what they're permitted to do or ask the AI to do — the same permission list either way.</p>
      </div>

      {error && <div className="error-banner">{error}</div>}

      <h3 style={{ fontSize: 13, textTransform: "uppercase", letterSpacing: ".05em", color: "var(--ink-dim)", margin: "0 0 10px" }}>
        Roles
      </h3>
      <div className="toolbar">
        <div />
        <button className="primary-btn" onClick={() => setShowRoleForm((v) => !v)}>
          {showRoleForm ? "Cancel" : "+ New role"}
        </button>
      </div>
      {showRoleForm && <RoleForm onDone={() => { setShowRoleForm(false); refresh(); }} />}
      {roles.length > 0 && (
        <div className="table-wrap" style={{ marginBottom: 28 }}>
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Permissions</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {roles.map((r) =>
                editingRoleId === r.id ? (
                  <tr key={r.id}>
                    <td colSpan={3}>
                      <RoleForm
                        role={r}
                        onDone={() => {
                          setEditingRoleId(null);
                          refresh();
                        }}
                      />
                    </td>
                  </tr>
                ) : (
                  <tr key={r.id}>
                    <td>{r.name}</td>
                    <td>
                      <div className="perm-grid">
                        {r.permissions.map((p) => (
                          <span key={p} className="perm-chip on" style={{ cursor: "default" }}>
                            {p}
                          </span>
                        ))}
                      </div>
                    </td>
                    <td>
                      <button className="secondary-btn" onClick={() => setEditingRoleId(r.id)}>
                        Edit
                      </button>
                    </td>
                  </tr>
                ),
              )}
            </tbody>
          </table>
        </div>
      )}

      <h3 style={{ fontSize: 13, textTransform: "uppercase", letterSpacing: ".05em", color: "var(--ink-dim)", margin: "0 0 10px" }}>
        Users
      </h3>
      <div className="toolbar">
        <div />
        <button className="primary-btn" disabled={roles.length === 0} onClick={() => setShowUserForm((v) => !v)}>
          {showUserForm ? "Cancel" : "+ New user"}
        </button>
      </div>
      {roles.length === 0 && !loading && (
        <p className="footnote">Create a role first — every user needs one.</p>
      )}
      {showUserForm && <UserForm roles={roles} onDone={() => { setShowUserForm(false); refresh(); }} />}

      {!loading && users.length === 0 && (
        <div className="card" style={{ textAlign: "center", color: "var(--ink-dim)" }}>
          No users yet.
        </div>
      )}

      {users.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Username</th>
                <th>Role</th>
                <th>Status</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) =>
                editingUserId === u.id ? (
                  <tr key={u.id}>
                    <td colSpan={5}>
                      <UserForm
                        roles={roles}
                        user={u}
                        onDone={() => {
                          setEditingUserId(null);
                          refresh();
                        }}
                      />
                    </td>
                  </tr>
                ) : (
                  <tr key={u.id}>
                    <td>{u.display_name}</td>
                    <td className="mono">{u.username}</td>
                    <td>{u.role_name ?? "—"}</td>
                    <td>
                      <span className={`badge ${u.active ? "status-confirmed" : "status-draft"}`}>
                        {u.active ? "Active" : "Deactivated"}
                      </span>
                    </td>
                    <td style={{ display: "flex", gap: 8 }}>
                      <button className="secondary-btn" onClick={() => setEditingUserId(u.id)}>
                        Edit
                      </button>
                      <button
                        className="secondary-btn"
                        disabled={u.id === currentUser?.id}
                        title={u.id === currentUser?.id ? "You can't deactivate your own account" : undefined}
                        onClick={async () => {
                          await updateAdminUser(u.id, { active: !u.active });
                          refresh();
                        }}
                      >
                        {u.active ? "Deactivate" : "Activate"}
                      </button>
                    </td>
                  </tr>
                ),
              )}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function RoleForm({ role, onDone }: { role?: Role; onDone: () => void }) {
  const [name, setName] = useState(role?.name ?? "");
  const [permissions, setPermissions] = useState<Set<string>>(new Set(role?.permissions ?? []));
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  function toggle(perm: string) {
    setPermissions((prev) => {
      const next = new Set(prev);
      if (next.has(perm)) next.delete(perm);
      else next.add(perm);
      return next;
    });
  }

  async function save() {
    setSaving(true);
    setError(null);
    try {
      if (role) await updateRole(role.id, { name, permissions: [...permissions] });
      else await createRole({ name, permissions: [...permissions] });
      onDone();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't save.");
    } finally {
      setSaving(false);
    }
  }

  const isSuperAdmin = permissions.has("*");

  return (
    <div className="card form-card">
      <label className="field">
        <span>Role name</span>
        <input value={name} onChange={(e) => setName(e.target.value)} autoFocus placeholder="e.g. Sales Rep" />
      </label>
      <div className="field">
        <span>Permissions</span>
        {isSuperAdmin ? (
          <p style={{ margin: "4px 0 0", fontSize: 12.5, color: "var(--ink-dim)" }}>
            This role has the <code className="mono">*</code> Super Admin permission — it bypasses every check, so
            individual permissions aren't listed. Remove <code className="mono">*</code> from the role's data
            directly if you need to convert it to a limited role.
          </p>
        ) : (
          <div className="perm-grid">
            {KNOWN_PERMISSIONS.map((p) => (
              <label key={p} className={`perm-chip${permissions.has(p) ? " on" : ""}`} title={PERMISSION_HINTS[p]}>
                <input type="checkbox" checked={permissions.has(p)} onChange={() => toggle(p)} />
                {p}
              </label>
            ))}
          </div>
        )}
      </div>
      {error && <div className="error-banner">{error}</div>}
      <div className="form-actions">
        <button className="primary-btn" disabled={!name.trim() || saving} onClick={save}>
          {saving ? "Saving…" : "Save role"}
        </button>
        <button className="secondary-btn" onClick={onDone}>
          Cancel
        </button>
      </div>
    </div>
  );
}

function UserForm({ roles, user, onDone }: { roles: Role[]; user?: AdminUser; onDone: () => void }) {
  const [displayName, setDisplayName] = useState(user?.display_name ?? "");
  const [username, setUsername] = useState(user?.username ?? "");
  const [password, setPassword] = useState("");
  const [email, setEmail] = useState(user?.email ?? "");
  const [roleId, setRoleId] = useState(user?.role_id ?? roles[0]?.id ?? "");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function save() {
    setSaving(true);
    setError(null);
    try {
      if (user) {
        await updateAdminUser(user.id, {
          display_name: displayName,
          role_id: roleId,
          email: email.trim(),
          ...(password ? { password } : {}),
        });
      } else {
        await createAdminUser({ username, display_name: displayName, password, role_id: roleId, email: email.trim() });
      }
      onDone();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't save.");
    } finally {
      setSaving(false);
    }
  }

  const canSave = displayName.trim() && roleId && (user ? true : username.trim() && password.length >= 8);

  return (
    <div className="card form-card">
      <div className="field-grid">
        <label className="field">
          <span>Name</span>
          <input value={displayName} onChange={(e) => setDisplayName(e.target.value)} autoFocus />
        </label>
        {!user && (
          <label className="field">
            <span>Username</span>
            <input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="off" />
          </label>
        )}
        <label className="field">
          <span>Email (for notifications)</span>
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="off" />
        </label>
        <label className="field">
          <span>{user ? "New password (optional)" : "Password"}</span>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="new-password"
            placeholder={user ? "leave blank to keep current" : undefined}
          />
        </label>
        <label className="field">
          <span>Role</span>
          <select value={roleId} onChange={(e) => setRoleId(e.target.value)}>
            {roles.map((r) => (
              <option key={r.id} value={r.id}>
                {r.name}
              </option>
            ))}
          </select>
        </label>
      </div>
      {error && <div className="error-banner">{error}</div>}
      <div className="form-actions">
        <button className="primary-btn" disabled={!canSave || saving} onClick={save}>
          {saving ? "Saving…" : "Save"}
        </button>
        <button className="secondary-btn" onClick={onDone}>
          Cancel
        </button>
      </div>
    </div>
  );
}
