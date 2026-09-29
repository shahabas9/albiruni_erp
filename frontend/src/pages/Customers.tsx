import { useCallback, useState } from "react";
import { ApiError, createCustomer, fetchCustomers, updateCustomer, type Customer, type DuplicateMatch } from "../api/client";
import { CsvImport } from "../components/CsvImport";
import { DuplicateWarning, Pager, SearchBox } from "../crm/ui";
import { useAppData } from "../data/AppDataProvider";
import { PAGE_SIZE, usePaged } from "../lib/usePaged";

type ActiveFilter = "all" | "active" | "inactive";

export function Customers() {
  const { can, version } = useAppData();
  const [importing, setImporting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const onSearch = useCallback((q: string) => setSearch(q), []);
  const [active, setActive] = useState<ActiveFilter>("all");
  const list = usePaged(
    (limit, offset) =>
      fetchCustomers({ q: search, active: active === "all" ? undefined : active === "active", limit, offset }),
    `${search}|${active}`,
    version,
  );
  const customers = list.rows;
  const refresh = list.reload;

  return (
    <section>
      <div className="page-head">
        <div className="eyebrow">Sales</div>
        <h1 className="page-title">Customers</h1>
        <p className="page-sub">Master data for who you sell to — resolved by name in quotations, whether typed or asked in natural language.</p>
      </div>

      {(error ?? list.error) && <div className="error-banner">{error ?? list.error}</div>}

      <div className="toolbar">
        <div className="filters" aria-label="Status filter">
          {(["all", "active", "inactive"] as const).map((f) => (
            <button key={f} className={active === f ? "on" : ""} onClick={() => setActive(f)}>
              {f === "all" ? "All" : f === "active" ? "Active" : "Inactive"}
            </button>
          ))}
        </div>
        <SearchBox value={search} onChange={onSearch} placeholder="Search name or GSTIN" />
        {can("sales.customer.write") && (
          <div style={{ display: "flex", gap: 8 }}>
            <button className="ghost-btn" onClick={() => setImporting(true)}>
              Import CSV
            </button>
            <button className="primary-btn" onClick={() => setShowForm((v) => !v)}>
              {showForm ? "Cancel" : "+ New customer"}
            </button>
          </div>
        )}
      </div>
      {importing && <CsvImport kind="customers" onClose={() => setImporting(false)} onImported={refresh} />}

      {showForm && <CustomerForm onDone={() => { setShowForm(false); refresh(); }} />}

      {!list.loading && list.total === 0 && !showForm && (
        <div className="card" style={{ textAlign: "center", color: "var(--ink-dim)" }}>
          {search || active !== "all" ? "No customers match this filter." : "No customers yet — add one above."}
        </div>
      )}

      {customers.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>GSTIN</th>
                <th>Credit limit</th>
                <th>Status</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {customers.map((c) =>
                editingId === c.id ? (
                  <tr key={c.id}>
                    <td colSpan={5}>
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
                    <td>{c.gstin ? <span className="mono">{c.gstin}</span> : <span className="followup none">Unregistered</span>}</td>
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
                          try {
                            await updateCustomer(c.id, { active: !c.active });
                            await refresh();
                          } catch (err) {
                            setError(err instanceof ApiError ? err.message : "Couldn't update.");
                          }
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
      <Pager page={list.page} pageSize={PAGE_SIZE} total={list.total} onPage={list.setPage} />
    </section>
  );
}

function CustomerForm({ customer, onDone }: { customer?: Customer; onDone: () => void }) {
  const [name, setName] = useState(customer?.name ?? "");
  const [creditLimit, setCreditLimit] = useState(String(customer?.credit_limit ?? 0));
  const [gstin, setGstin] = useState(customer?.gstin ?? "");
  const [error, setError] = useState<string | null>(null);
  const [duplicates, setDuplicates] = useState<DuplicateMatch[] | null>(null);
  const [saving, setSaving] = useState(false);

  async function save(allowDuplicate = false) {
    setSaving(true);
    setError(null);
    try {
      if (customer) {
        await updateCustomer(customer.id, { name, credit_limit: Number(creditLimit), gstin });
      } else {
        await createCustomer({ name, credit_limit: Number(creditLimit), gstin, allow_duplicate: allowDuplicate });
      }
      onDone();
    } catch (err) {
      if (err instanceof ApiError && err.duplicates) setDuplicates(err.duplicates);
      else setError(err instanceof ApiError ? err.message : "Couldn't save.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="card form-card">
      <div className="field-grid">
        <label className="field">
          <span>Name</span>
          <input value={name} onChange={(e) => (setName(e.target.value), setDuplicates(null))} autoFocus />
        </label>
        <label className="field">
          <span>Credit limit (₹)</span>
          <input type="number" min={0} value={creditLimit} onChange={(e) => setCreditLimit(e.target.value)} />
        </label>
        <label className="field">
          <span>GSTIN (optional)</span>
          <input
            value={gstin}
            onChange={(e) => (setGstin(e.target.value.toUpperCase()), setDuplicates(null))}
            maxLength={15}
            placeholder="e.g. 32ABCDE1234F1Z9"
            style={{ fontFamily: "IBM Plex Mono, monospace", letterSpacing: "0.04em" }}
          />
        </label>
      </div>
      {error && <div className="error-banner">{error}</div>}
      {duplicates && (
        <DuplicateWarning noun="customer" matches={duplicates} busy={saving} onCreate={() => save(true)} onBack={() => setDuplicates(null)} />
      )}
      <div className="form-actions" hidden={Boolean(duplicates)}>
        <button className="primary-btn" disabled={!name.trim() || saving} onClick={() => save()}>
          {saving ? "Saving…" : "Save"}
        </button>
        <button className="secondary-btn" onClick={onDone}>
          Cancel
        </button>
      </div>
    </div>
  );
}
