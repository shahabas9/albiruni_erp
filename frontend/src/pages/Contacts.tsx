import { useEffect, useState } from "react";
import { ApiError, createContact, fetchContacts, fetchCustomers, updateContact, type Contact, type Customer } from "../api/client";
import { CustomerPicker } from "../components/CustomerPicker";
import { ContactActions } from "../crm/ContactActions";

export function Contacts() {
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);

  async function refresh() {
    setLoading(true);
    try {
      const [c, cu] = await Promise.all([fetchContacts(), fetchCustomers()]);
      setContacts(c);
      setCustomers(cu);
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
        <div className="eyebrow">CRM</div>
        <h1 className="page-title">Contacts</h1>
        <p className="page-sub">People at your customers — who you actually talk to, distinct from the account itself.</p>
      </div>

      {error && <div className="error-banner">{error}</div>}

      <div className="toolbar">
        <div />
        <button className="primary-btn" onClick={() => setShowForm((v) => !v)}>
          {showForm ? "Cancel" : "+ New contact"}
        </button>
      </div>

      {showForm && (
        <ContactForm
          customers={customers}
          onCustomerCreated={(c) => setCustomers((prev) => [...prev, c])}
          onDone={() => {
            setShowForm(false);
            refresh();
          }}
        />
      )}

      {!loading && contacts.length === 0 && !showForm && (
        <div className="card" style={{ textAlign: "center", color: "var(--ink-dim)" }}>
          No contacts yet.
        </div>
      )}

      {contacts.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Customer</th>
                <th>Title</th>
                <th>Email</th>
                <th>Phone</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {contacts.map((c) =>
                editingId === c.id ? (
                  <tr key={c.id}>
                    <td colSpan={6}>
                      <ContactForm
                        customers={customers}
                        contact={c}
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
                    <td>{c.customer_name}</td>
                    <td>{c.title || "—"}</td>
                    <td>{c.email || "—"}</td>
                    <td>
                      <div className="cell-with-actions">
                        <span>{c.phone || "—"}</span>
                        <ContactActions phone={c.phone} name={c.name} target={{ customer_id: c.customer_id }} />
                      </div>
                    </td>
                    <td>
                      <button className="secondary-btn" onClick={() => setEditingId(c.id)}>
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
    </section>
  );
}

function ContactForm({
  customers,
  contact,
  onCustomerCreated,
  onDone,
}: {
  customers: Customer[];
  contact?: Contact;
  onCustomerCreated?: (customer: Customer) => void;
  onDone: () => void;
}) {
  const [localCustomers, setLocalCustomers] = useState(customers);
  const [customerId, setCustomerId] = useState(contact?.customer_id ?? customers[0]?.id ?? "");
  const [name, setName] = useState(contact?.name ?? "");
  const [title, setTitle] = useState(contact?.title ?? "");
  const [email, setEmail] = useState(contact?.email ?? "");
  const [phone, setPhone] = useState(contact?.phone ?? "");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function save() {
    setSaving(true);
    setError(null);
    try {
      if (contact) {
        await updateContact(contact.id, { name, title, email, phone });
      } else {
        await createContact({ customer_id: customerId, name, title, email, phone });
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
        {!contact && (
          <CustomerPicker
            customers={localCustomers}
            value={customerId}
            onChange={setCustomerId}
            onCustomerCreated={(c) => {
              setLocalCustomers((prev) => [...prev, c]);
              onCustomerCreated?.(c);
            }}
          />
        )}
        <label className="field">
          <span>Name</span>
          <input value={name} onChange={(e) => setName(e.target.value)} autoFocus={!!contact} />
        </label>
        <label className="field">
          <span>Title</span>
          <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. Purchase Manager" />
        </label>
        <label className="field">
          <span>Email</span>
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
        </label>
        <label className="field">
          <span>Phone</span>
          <input value={phone} onChange={(e) => setPhone(e.target.value)} />
        </label>
      </div>
      {error && <div className="error-banner">{error}</div>}
      <div className="form-actions">
        <button className="primary-btn" disabled={!name.trim() || !customerId || saving} onClick={save}>
          {saving ? "Saving…" : "Save"}
        </button>
        <button className="secondary-btn" onClick={onDone}>
          Cancel
        </button>
      </div>
    </div>
  );
}
