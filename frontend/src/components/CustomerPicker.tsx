import { useState } from "react";
import { ApiError, createCustomer, type Customer } from "../api/client";

const CREATE_NEW = "__create_new__";

/** A customer <select> that can create a customer inline, without leaving
 * the current form. Customer is shared master data (Sales and CRM both
 * depend on it) — CRM screens shouldn't force a detour to the Sales menu
 * just to add one. Credit limit is deliberately not asked here: it
 * defaults to 0 and stays editable later from the Customers page. */
export function CustomerPicker({
  customers,
  value,
  onChange,
  onCustomerCreated,
}: {
  customers: Customer[];
  value: string;
  onChange: (customerId: string) => void;
  onCustomerCreated: (customer: Customer) => void;
}) {
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function confirmCreate() {
    setSaving(true);
    setError(null);
    try {
      const customer = await createCustomer({ name, credit_limit: 0 });
      onCustomerCreated(customer);
      onChange(customer.id);
      setCreating(false);
      setName("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't create customer.");
    } finally {
      setSaving(false);
    }
  }

  if (creating) {
    return (
      <label className="field" style={{ gridColumn: "1 / -1" }}>
        <span>New customer name</span>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            autoFocus
            placeholder="Company or account name"
            style={{ flex: "1 1 180px" }}
            onKeyDown={(e) => e.key === "Enter" && name.trim() && confirmCreate()}
          />
          <button
            type="button"
            className="primary-btn"
            style={{ flex: "none" }}
            disabled={!name.trim() || saving}
            onClick={confirmCreate}
          >
            {saving ? "Adding…" : "Add"}
          </button>
          <button
            type="button"
            className="secondary-btn"
            style={{ flex: "none" }}
            onClick={() => {
              setCreating(false);
              setName("");
              setError(null);
            }}
          >
            Cancel
          </button>
        </div>
        {error && <div className="error-banner">{error}</div>}
      </label>
    );
  }

  return (
    <label className="field">
      <span>Customer</span>
      <select
        value={value}
        onChange={(e) => {
          if (e.target.value === CREATE_NEW) setCreating(true);
          else onChange(e.target.value);
        }}
      >
        {customers.length === 0 && <option value="">No customers yet</option>}
        {customers.map((c) => (
          <option key={c.id} value={c.id}>
            {c.name}
          </option>
        ))}
        <option value={CREATE_NEW}>+ Create new customer…</option>
      </select>
    </label>
  );
}
