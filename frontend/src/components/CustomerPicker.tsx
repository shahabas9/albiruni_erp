import { useCallback, useEffect, useState } from "react";
import { ApiError, createCustomer, fetchCustomers, type Customer, type DuplicateMatch } from "../api/client";
import { DuplicateWarning, SearchBox } from "../crm/ui";

const CREATE_NEW = "__create_new__";
const PICK_LIMIT = 20;

/** A customer picker that searches the server (so it works with any number
 * of customers) and can create a customer inline, without leaving the
 * current form. Customer is shared master data (Sales and CRM both depend
 * on it) — CRM screens shouldn't force a detour to the Sales menu just to
 * add one. Credit limit is deliberately not asked here: it defaults to 0
 * and stays editable later from the Customers page.
 *
 * With no value, the first customer is picked; while searching, the first
 * match is — so the chosen customer is always the one on screen. */
export function CustomerPicker({
  value,
  selectedName,
  onChange,
}: {
  value: string;
  /** The current customer's name, when the form starts with one. */
  selectedName?: string;
  onChange: (customerId: string) => void;
}) {
  const [search, setSearch] = useState("");
  const onSearch = useCallback((q: string) => setSearch(q), []);
  // The rows and the search they answer, so a late response can't be read as the current search's.
  const [result, setResult] = useState<{ q: string; rows: Customer[] } | null>(null);
  const options = result?.rows ?? null;
  const [selected, setSelected] = useState<{ id: string; name: string } | null>(
    value && selectedName ? { id: value, name: selectedName } : null,
  );
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [duplicates, setDuplicates] = useState<DuplicateMatch[] | null>(null);
  const [saving, setSaving] = useState(false);
  // True from the first keystroke until that search's results are in. The
  // selection is cleared meanwhile, so Save (which needs a customer) can't
  // file the record under the customer picked before the search.
  const [pending, setPending] = useState(false);

  useEffect(() => {
    let current = true;
    fetchCustomers({ q: search, active: true, limit: PICK_LIMIT })
      .then((page) => current && setResult({ q: search, rows: page.rows }))
      .catch((err) => {
        if (!current) return;
        setPending(false);
        setError(err instanceof ApiError ? err.message : "Couldn't load customers.");
      });
    return () => {
      current = false;
    };
  }, [search]);

  function pick(customer: { id: string; name: string }) {
    setSelected(customer);
    onChange(customer.id);
  }

  function clear() {
    setSelected(null);
    if (value) onChange("");
  }

  // The selection is always visible in the list: with no search, keep it
  // (or take the first customer); while searching, follow the first match,
  // and clear it when nothing matches rather than keep a hidden choice.
  function applyResult(r: { q: string; rows: Customer[] }, current: string) {
    const inList = r.rows.some((c) => c.id === current);
    if (r.q) {
      if (inList) return;
      if (r.rows[0]) pick(r.rows[0]);
      else clear();
    } else if (!current && r.rows[0]) {
      pick(r.rows[0]);
    }
  }

  useEffect(() => {
    if (!result || result.q !== search) return; // an older search's answer
    setPending(false);
    applyResult(result, value);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [result]);

  function onTyping(text: string) {
    if (result && text === result.q) {
      // Back to what's already listed: no new search will run, so apply it now.
      setPending(false);
      applyResult(result, "");
      return;
    }
    setPending(true);
    clear();
  }

  /** Select a customer and make it the one match on screen (e.g. just created). */
  function show(customer: Customer) {
    setSearch(customer.name);
    setResult({ q: customer.name, rows: [customer] });
    pick(customer);
  }

  function close() {
    setCreating(false);
    setName("");
    setError(null);
    setDuplicates(null);
  }

  async function confirmCreate(allowDuplicate = false) {
    setSaving(true);
    setError(null);
    try {
      const customer = await createCustomer({ name, credit_limit: 0, allow_duplicate: allowDuplicate });
      show(customer);
      close();
    } catch (err) {
      if (err instanceof ApiError && err.duplicates) setDuplicates(err.duplicates);
      else setError(err instanceof ApiError ? err.message : "Couldn't create customer.");
    } finally {
      setSaving(false);
    }
  }

  if (creating) {
    return (
      <div className="field" style={{ gridColumn: "1 / -1" }}>
        <span>New customer name</span>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          <input
            value={name}
            onChange={(e) => (setName(e.target.value), setDuplicates(null))}
            autoFocus
            placeholder="Company or account name"
            aria-label="New customer name"
            style={{ flex: "1 1 180px" }}
            onKeyDown={(e) => e.key === "Enter" && name.trim() && !duplicates && confirmCreate()}
          />
          <button
            type="button"
            className="primary-btn"
            style={{ flex: "none" }}
            disabled={!name.trim() || saving || Boolean(duplicates)}
            onClick={() => confirmCreate()}
          >
            {saving ? "Adding…" : "Add"}
          </button>
          <button type="button" className="secondary-btn" style={{ flex: "none" }} onClick={close}>
            Cancel
          </button>
        </div>
        {error && <div className="error-banner">{error}</div>}
        {duplicates && (
          <DuplicateWarning
            noun="customer"
            matches={duplicates}
            busy={saving}
            onCreate={() => confirmCreate(true)}
            onBack={() => setDuplicates(null)}
            onUse={(id) => {
              const match = duplicates.find((m) => m.id === id);
              if (match?.detail.includes("inactive")) {
                setDuplicates(null);
                setError(`${match.label} is inactive — reactivate it on the Customers page first.`);
                return;
              }
              show({
                id, name: match?.label ?? "", gstin: "", credit_limit: 0, active: true, tags: [], custom: {},
                billing_address: "", shipping_address: "", state_code: "", payment_terms_days: null, email: "", phone: "", price_list_id: null, country: "", vat_number: "", name_ar: "",
                building_no: "", street: "", district: "", city: "", postal_code: "",
              });
              close();
            }}
          />
        )}
      </div>
    );
  }

  const shown = options ?? [];
  // A customer chosen earlier (or the record's own) that isn't on the first page.
  const selectedMissing = !search && selected && selected.id === value && !shown.some((c) => c.id === value);

  return (
    <div className="field">
      <span>Customer</span>
      <SearchBox value={search} onChange={onSearch} onTyping={onTyping} placeholder="Search customers…" />
      <select
        value={value}
        aria-label="Customer"
        onChange={(e) => {
          if (e.target.value === CREATE_NEW) {
            setName(search);
            setCreating(true);
            return;
          }
          const customer = shown.find((c) => c.id === e.target.value);
          if (customer) pick(customer);
        }}
      >
        {!value && (
          <option value="">
            {pending ? "Searching…" : options === null ? "Loading…" : search ? "No match" : "No customers yet"}
          </option>
        )}
        {selectedMissing && <option value={selected.id}>{selected.name}</option>}
        {!pending && shown.map((c) => (
          <option key={c.id} value={c.id}>
            {c.name}
          </option>
        ))}
        <option value={CREATE_NEW}>+ Create new customer{search ? ` “${search}”` : ""}…</option>
      </select>
      {error && <div className="error-banner">{error}</div>}
    </div>
  );
}
