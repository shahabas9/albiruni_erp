import { useEffect, useState } from "react";
import { ApiError, createCustomer, fetchCustomers, updateCustomer, type Customer } from "../api/client";

export function Customers() {
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);

  async function refresh() {
    setLoading(true);
    try {
      setCustomers(await fetchCustomers());
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
        <div className="eyebrow">Sales</div>
        <h1 className="page-title">Customers</h1>
        <p className="page-sub">Master data for who you sell to — resolved by name in quotations, whether typed or asked in natural language.</p>
      </div>

      {error && <div className="error-banner">{error}</div>}

      <div className="toolbar">
        <div />
        <button className="primary-btn" onClick={() => setShowForm((v) => !v)}>
          {showForm ? "Cancel" : "+ New customer"}
        </button>
      </div>

      {showForm && <CustomerForm onDone={() => { setShowForm(false); refresh(); }} />}

      {!loading && customers.length === 0 && !showForm && (
        <div className="card" style={{ textAlign: "center", color: "var(--ink-dim)" }}>
          No customers yet — add one above.
        </div>
      )}

      {customers.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Credit limit</th>
                <th>Status</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {customers.map((c) =>
                editingId === c.id ? (
                  <tr key={c.id}>
                    <td colSpan={4}>
                      <CustomerForm
                        customer={c}
                        onDone={() => {
                          setEditingId(null);
                          refresh();
                        }}
                      />
                    </td>
                  </tr>
                ) : (
                  <tr key={c.id}>
                    <td>{c.name}</td>
                    <td className="mono">₹{c.credit_limit.toLocaleString("en-IN")}</td>
                    <td>
                      <span className={`badge ${c.active ? "status-confirmed" : "status-draft"}`}>
                        {c.active ? "Active" : "Inactive"}
                      </span>
                    </td>
                    <td style={{ display: "flex", gap: 8 }}>
                      <button className="secondary-btn" onClick={() => setEditingId(c.id)}>
                        Edit
                      </button>
                      <button
                        className="secondary-btn"
                        onClick={async () => {
                          await updateCustomer(c.id, { active: !c.active });
                          refresh();
                        }}
                      >
                        {c.active ? "Deactivate" : "Activate"}
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

function CustomerForm({ customer, onDone }: { customer?: Customer; onDone: () => void }) {
  const [name, setName] = useState(customer?.name ?? "");
  const [creditLimit, setCreditLimit] = useState(String(customer?.credit_limit ?? 0));
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function save() {
    setSaving(true);
    setError(null);
    try {
      if (customer) {
        await updateCustomer(customer.id, { name, credit_limit: Number(creditLimit) });
      } else {
        await createCustomer({ name, credit_limit: Number(creditLimit) });
      }
      onDone();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't save.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="card form-card">
      <div className="field-grid">
        <label className="field">
          <span>Name</span>
          <input value={name} onChange={(e) => setName(e.target.value)} autoFocus />
        </label>
        <label className="field">
          <span>Credit limit (₹)</span>
          <input type="number" min={0} value={creditLimit} onChange={(e) => setCreditLimit(e.target.value)} />
        </label>
      </div>
      {error && <div className="error-banner">{error}</div>}
      <div className="form-actions">
        <button className="primary-btn" disabled={!name.trim() || saving} onClick={save}>
          {saving ? "Saving…" : "Save"}
        </button>
        <button className="secondary-btn" onClick={onDone}>
          Cancel
        </button>
      </div>
    </div>
  );
}
