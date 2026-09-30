import { useCallback, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, createContact, deleteContact, fetchContacts, updateContact, type Contact } from "../api/client";
import { CustomerPicker } from "../components/CustomerPicker";
import { SavedViews } from "../components/SavedViews";
import { recallFilters } from "../lib/filterMemory";
import { ExportButton } from "../components/ExportButton";
import { ContactActions } from "../crm/ContactActions";
import { Pager, SearchBox } from "../crm/ui";
import { useAppData } from "../data/AppDataProvider";
import { PAGE_SIZE, usePaged } from "../lib/usePaged";

export function Contacts() {
  const { version } = useAppData();
  const [exportError, setExportError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [search, setSearch] = useState(() => String(recallFilters("contacts").search ?? ""));
  const onSearch = useCallback((q: string) => setSearch(q), []);
  const list = usePaged((limit, offset) => fetchContacts({ q: search, limit, offset }), search, version);
  const contacts = list.rows;
  const refresh = list.reload;

  return (
    <section>
      <div className="page-head">
        <div className="eyebrow">CRM</div>
        <h1 className="page-title">Contacts</h1>
        <p className="page-sub">People at your customers — who you actually talk to, distinct from the account itself.</p>
      </div>

      {(list.error ?? exportError) && <div className="error-banner">{list.error ?? exportError}</div>}

      <div className="toolbar">
        <SavedViews page="contacts" filters={{ search }} onApply={(f) => setSearch(String(f.search ?? ""))} />
        <SearchBox value={search} onChange={onSearch} placeholder="Search name, customer, phone, email" />
        <ExportButton kind="contacts" filters={{ q: search }} onError={setExportError} />
        <button className="primary-btn" onClick={() => setShowForm((v) => !v)}>
          {showForm ? "Cancel" : "+ New contact"}
        </button>
      </div>

      {showForm && (
        <ContactForm
          onDone={() => {
            setShowForm(false);
            refresh();
          }}
        />
      )}

      {!list.loading && list.total === 0 && !showForm && (
        <div className="card" style={{ textAlign: "center", color: "var(--ink-dim)" }}>
          {search ? "No contacts match this search." : "No contacts yet."}
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
                    <td>
                      <Link to={`/customers/${c.customer_id}`}>{c.customer_name}</Link>
                    </td>
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
                      </button>{" "}
                      <button
                        className="danger-btn sm"
                        onClick={async () => {
                          if (!window.confirm(`Delete ${c.name}?`)) return;
                          await deleteContact(c.id);
                          await refresh();
                        }}
                      >
                        Delete
                      </button>
                    </td>
                  </tr>
                ),
              )}
            </tbody>
          </table>
        </div>
      )}
      <Pager page={list.page} pageSize={PAGE_SIZE} total={list.total} onPage={list.setPage} />
    </section>
  );
}

function ContactForm({ contact, onDone }: { contact?: Contact; onDone: () => void }) {
  const [customerId, setCustomerId] = useState(contact?.customer_id ?? "");
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
          <CustomerPicker value={customerId} onChange={setCustomerId} />
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
