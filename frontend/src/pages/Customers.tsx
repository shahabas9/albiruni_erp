import { useCallback, useState } from "react";
import { Link } from "react-router-dom";
import {
  ApiError,
  bulkAction,
  createCustomer,
  deleteCustomer,
  fetchCustomerDuplicates,
  fetchCustomers,
  mergeCustomers,
  updateCustomer, type Customer, type CustomValues, type DuplicateMatch } from "../api/client";
import { CsvImport } from "../components/CsvImport";
import { StateSelect } from "../components/StateSelect";
import { SavedViews } from "../components/SavedViews";
import { recallFilters } from "../lib/filterMemory";
import { ExportButton } from "../components/ExportButton";
import { CustomFieldInputs, TagChips, TagFilter, TagInput, changedCustom, useCustomFields } from "../crm/fields";
import { Attachments } from "../crm/Attachments";
import { BulkBar, useSelection, type BulkActionDef } from "../crm/BulkBar";
import { MergeDuplicates } from "../crm/MergeDuplicates";
import { Drawer, DuplicateWarning, Pager, SearchBox } from "../crm/ui";
import { useAppData } from "../data/AppDataProvider";
import { PAGE_SIZE, usePaged } from "../lib/usePaged";

type ActiveFilter = "all" | "active" | "inactive";

export function Customers() {
  const { can, version } = useAppData();
  const [importing, setImporting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [saved] = useState(() => recallFilters("customers"));
  const [search, setSearch] = useState(String(saved.search ?? ""));
  const onSearch = useCallback((q: string) => setSearch(q), []);
  const [active, setActive] = useState<ActiveFilter>((saved.active as ActiveFilter) || "all");
  const [tag, setTag] = useState(String(saved.tag ?? ""));
  const [filesFor, setFilesFor] = useState<Customer | null>(null);
  const [findingDupes, setFindingDupes] = useState(false);

  async function removeCustomer(c: Customer) {
    if (!window.confirm(`Delete ${c.name}? Its contacts, notes and files go too. This can't be undone.`)) return;
    setError(null);
    try {
      await deleteCustomer(c.id);
      await refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't delete.");
    }
  }
  const list = usePaged(
    (limit, offset) =>
      fetchCustomers({ q: search, active: active === "all" ? undefined : active === "active", tag, limit, offset }),
    `${search}|${active}|${tag}`,
    version,
  );
  const customers = list.rows;
  const sel = useSelection(customers.map((c) => c.id), `${search}|${active}|${tag}|${list.page}`);
  const bulkEnabled = can("sales.customer.write") || can("sales.customer.delete");
  const bulkActions: BulkActionDef[] = [
    ...(can("sales.customer.write")
      ? [
          { key: "add_tag", label: "Add tag", input: "tag" as const },
          { key: "remove_tag", label: "Remove tag", input: "tag" as const },
          { key: "deactivate", label: "Deactivate", input: "none" as const },
          { key: "activate", label: "Activate", input: "none" as const },
        ]
      : []),
    ...(can("sales.customer.delete") ? [{ key: "delete", label: "Delete", input: "none" as const, danger: true }] : []),
  ];
  // Saves here reload only this list, so bump the tag filter's suggestions too.
  const [saves, setSaves] = useState(0);
  const refresh = async () => {
    setSaves((n) => n + 1);
    await list.reload();
  };

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
        <SavedViews
          page="customers"
          filters={{ active, tag, search }}
          onApply={(f) => {
            setActive(((f.active as ActiveFilter) || "all") as ActiveFilter);
            setTag(String(f.tag ?? ""));
            setSearch(String(f.search ?? ""));
          }}
        />
        <TagFilter recordType="customer" value={tag} onChange={setTag} version={version + saves} />
        <SearchBox value={search} onChange={onSearch} placeholder="Search name or GSTIN" />
        <ExportButton
          kind="customers"
          filters={{ q: search, active: active === "all" ? undefined : active === "active", tag }}
          onError={setError}
        />
        {can("sales.customer.write") && (
          <div style={{ display: "flex", gap: 8 }}>
            <button className="ghost-btn" onClick={() => setImporting(true)}>
              Import CSV
            </button>
            {can("sales.customer.delete") && (
              <button className="ghost-btn" onClick={() => setFindingDupes(true)}>
                Find duplicates
              </button>
            )}
            <button className="primary-btn" onClick={() => setShowForm((v) => !v)}>
              {showForm ? "Cancel" : "+ New customer"}
            </button>
          </div>
        )}
      </div>
      {importing && <CsvImport kind="customers" onClose={() => setImporting(false)} onImported={refresh} />}

      {showForm && <CustomerForm onDone={() => { setShowForm(false); refresh(); }} />}

      {bulkEnabled && (
        <BulkBar
          selection={sel}
          total={list.total}
          noun="customer"
          actions={bulkActions}
          assignees={[]}
          run={(action, value, _lost, target) =>
            bulkAction("customers", {
              action,
              value,
              ...(target.all
                ? { filters: { q: search, active: active === "all" ? undefined : active === "active", tag } }
                : { ids: target.ids }),
            })
          }
          onDone={() => void refresh()}
        />
      )}

      {!list.loading && list.total === 0 && !showForm && (
        <div className="card" style={{ textAlign: "center", color: "var(--ink-dim)" }}>
          {search || tag || active !== "all" ? "No customers match this filter." : "No customers yet — add one above."}
        </div>
      )}

      {customers.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                {bulkEnabled && (
                  <th className="check-col">
                    <input type="checkbox" aria-label="Select all on this page" checked={sel.allOnPage} onChange={sel.togglePage} />
                  </th>
                )}
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
                    <td colSpan={bulkEnabled ? 6 : 5}>
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
                  <tr key={c.id} className={sel.has(c.id) ? "selected" : undefined}>
                    {bulkEnabled && (
                      <td className="check-col">
                        <input type="checkbox" aria-label={`Select ${c.name}`} checked={sel.has(c.id)} onChange={() => sel.toggle(c.id)} />
                      </td>
                    )}
                    <td>
                      <Link className="link-btn" style={{ padding: 0 }} to={`/customers/${c.id}`}>
                        {c.name}
                      </Link>
                      <TagChips tags={c.tags} onClick={setTag} />
                    </td>
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
                      <button className="secondary-btn" onClick={() => setFilesFor(c)}>
                        Files
                      </button>
                      {can("sales.customer.delete") && (
                        <button className="danger-btn sm" onClick={() => removeCustomer(c)}>
                          Delete
                        </button>
                      )}
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

      {findingDupes && (
        <MergeDuplicates
          noun="customer"
          explain="Customers that share a name or GSTIN. Everything on the others — contacts, deals, quotations, follow-ups, files and history — moves to the one you keep."
          load={async () =>
            (await fetchCustomerDuplicates()).map((g) => ({
              reason: g.reason,
              records: g.customers.map((c) => ({
                id: c.id,
                title: c.name,
                detail: [c.gstin || "No GSTIN", c.active ? "Active" : "Inactive", c.tags.join(", ")].filter(Boolean).join(" · "),
              })),
            }))
          }
          merge={mergeCustomers}
          onMerged={() => void refresh()}
          onClose={() => setFindingDupes(false)}
        />
      )}

      {filesFor && (
        <Drawer title={filesFor.name} subtitle="Files" onClose={() => setFilesFor(null)}>
          <Attachments recordType="customer" recordId={filesFor.id} canWrite={can("sales.customer.write")} />
        </Drawer>
      )}
    </section>
  );
}

export function CustomerForm({ customer, onDone }: { customer?: Customer; onDone: () => void }) {
  const [name, setName] = useState(customer?.name ?? "");
  const [creditLimit, setCreditLimit] = useState(String(customer?.credit_limit ?? 0));
  const [gstin, setGstin] = useState(customer?.gstin ?? "");
  const [tags, setTags] = useState<string[]>(customer?.tags ?? []);
  const [billing, setBilling] = useState(customer?.billing_address ?? "");
  const [shipping, setShipping] = useState(customer?.shipping_address ?? "");
  const [state, setState] = useState(customer?.state_code ?? "");
  const [terms, setTerms] = useState(customer?.payment_terms_days == null ? "" : String(customer.payment_terms_days));
  // A registered customer's state is fixed by their GSTIN.
  const gstinState = /^\d{2}/.test(gstin.trim()) && gstin.trim().length === 15 ? gstin.trim().slice(0, 2) : "";
  const gstFields = {
    billing_address: billing,
    shipping_address: shipping,
    state_code: gstinState || state,
    payment_terms_days: terms === "" ? null : Number(terms),
  };
  const customFields = useCustomFields("customer");
  const [custom, setCustom] = useState<CustomValues>(customer?.custom ?? {});
  const [error, setError] = useState<string | null>(null);
  const [duplicates, setDuplicates] = useState<DuplicateMatch[] | null>(null);
  const [saving, setSaving] = useState(false);

  async function save(allowDuplicate = false) {
    setSaving(true);
    setError(null);
    try {
      if (customer) {
        await updateCustomer(customer.id, {
          name,
          credit_limit: Number(creditLimit),
          gstin,
          tags,
          custom: changedCustom(customer.custom, custom),
          ...gstFields,
        });
      } else {
        await createCustomer({
          name,
          credit_limit: Number(creditLimit),
          gstin,
          tags,
          custom,
          allow_duplicate: allowDuplicate,
          ...gstFields,
        });
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
        <label className="field">
          <span>State (place of supply)</span>
          <StateSelect value={gstinState || state} onChange={setState} disabled={Boolean(gstinState)} />
        </label>
        <label className="field">
          <span>Payment terms (days)</span>
          <input type="number" min={0} max={365} value={terms} onChange={(e) => setTerms(e.target.value)} placeholder="Company default" />
        </label>
        <label className="field full">
          <span>Billing address</span>
          <textarea rows={2} value={billing} onChange={(e) => setBilling(e.target.value)} />
        </label>
        <label className="field full">
          <span>Shipping address (if different)</span>
          <textarea rows={2} value={shipping} onChange={(e) => setShipping(e.target.value)} />
        </label>
        <CustomFieldInputs fields={customFields} values={custom} onChange={setCustom} />
        <div className="field full">
          <span>Tags</span>
          <TagInput value={tags} onChange={setTags} recordType="customer" />
        </div>
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
