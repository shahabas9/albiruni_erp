import { useEffect, useState } from "react";
import { ApiError, fetchSalesItems, type Item } from "../api/client";
import { deletePriceList, fetchPriceLists, savePriceList, type PriceList } from "../api/sales";
import { Icon } from "../components/Icon";
import { ErrorNote } from "../crm/ui";
import { useAppData } from "../data/AppDataProvider";
import { inr } from "../lib/format";

interface EditRow {
  item_id: string;
  min_qty: string;
  unit_price: string;
}

/** Agreed prices per customer group, with quantity breaks. */
export function PriceLists() {
  const { can } = useAppData();
  const canEdit = can("sales.settings.write");
  const [lists, setLists] = useState<PriceList[] | null>(null);
  const [items, setItems] = useState<Item[]>([]);
  const [editing, setEditing] = useState<PriceList | "new" | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function refresh() {
    try {
      const [l, its] = await Promise.all([fetchPriceLists(), fetchSalesItems()]);
      setLists(l);
      setItems(its);
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't load price lists.");
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  return (
    <section>
      <div className="page-head">
        <div className="eyebrow">Sales</div>
        <h1 className="page-title">Price lists</h1>
        <p className="page-sub">
          Agreed prices for dealers, distributors or key accounts, with lower prices for bigger quantities. A customer pays their
          own list, else the default list, else the item's price. Selling below it needs a manager.
        </p>
      </div>
      <ErrorNote message={error} />
      {canEdit && !editing && (
        <div className="toolbar">
          <div />
          <button className="primary-btn" onClick={() => setEditing("new")}>
            + New price list
          </button>
        </div>
      )}
      {editing && (
        <PriceListForm
          list={editing === "new" ? null : editing}
          items={items}
          onDone={() => {
            setEditing(null);
            refresh();
          }}
        />
      )}
      {lists && lists.length === 0 && !editing && (
        <div className="card" style={{ textAlign: "center", color: "var(--ink-dim)" }}>
          No price lists yet — everyone pays the item prices.
        </div>
      )}
      {lists && lists.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Prices</th>
                <th>Customers</th>
                <th>Status</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {lists.map((l) => (
                <tr key={l.id}>
                  <td>
                    {l.name} {l.is_default && <span className="badge status-confirmed">Default</span>}
                  </td>
                  <td>
                    {l.rows.length === 0
                      ? "—"
                      : l.rows
                          .slice(0, 3)
                          .map((r) => `${r.item_name} ${inr(r.unit_price)}${r.min_qty > 1 ? ` from ${r.min_qty}` : ""}`)
                          .join(" · ") + (l.rows.length > 3 ? ` · +${l.rows.length - 3} more` : "")}
                  </td>
                  <td className="mono">{l.is_default ? "Everyone else" : l.customers}</td>
                  <td>{l.active ? "On" : <span className="badge status-pending">Off</span>}</td>
                  <td>
                    {canEdit && (
                      <button className="secondary-btn" onClick={() => setEditing(l)}>
                        Edit
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function PriceListForm({ list, items, onDone }: { list: PriceList | null; items: Item[]; onDone: () => void }) {
  const [name, setName] = useState(list?.name ?? "");
  const [active, setActive] = useState(list?.active ?? true);
  const [isDefault, setIsDefault] = useState(list?.is_default ?? false);
  const [rows, setRows] = useState<EditRow[]>(
    list?.rows.map((r) => ({ item_id: r.item_id, min_qty: String(r.min_qty), unit_price: String(r.unit_price) })) ?? [],
  );
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const update = (idx: number, patch: Partial<EditRow>) => setRows(rows.map((r, i) => (i === idx ? { ...r, ...patch } : r)));
  const valid = name.trim() && rows.every((r) => r.item_id && Number(r.min_qty) > 0 && r.unit_price !== "" && Number(r.unit_price) >= 0);

  async function save() {
    setSaving(true);
    setError(null);
    try {
      await savePriceList(list?.id ?? null, {
        name: name.trim(),
        active,
        is_default: isDefault,
        rows: rows.map((r) => ({ item_id: r.item_id, min_qty: Number(r.min_qty), unit_price: Number(r.unit_price) })),
      });
      onDone();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't save.");
    } finally {
      setSaving(false);
    }
  }

  async function remove() {
    if (!list || !window.confirm(`Delete the price list “${list.name}”?`)) return;
    try {
      await deletePriceList(list.id);
      onDone();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't delete.");
    }
  }

  return (
    <div className="card form-card">
      <div className="field-grid">
        <label className="field">
          <span>Name</span>
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Dealers" autoFocus />
        </label>
        <label className="field checkbox-field">
          <input type="checkbox" checked={isDefault} onChange={(e) => setIsDefault(e.target.checked)} />
          <span>Default — for customers without a list of their own</span>
        </label>
        <label className="field checkbox-field">
          <input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} />
          <span>On (switched off, its customers pay the default prices)</span>
        </label>
      </div>
      <div className="line-items price-rows">
        <div className="line-items-head">
          <span>Item</span>
          <span>From qty</span>
          <span>Price (₹, before GST)</span>
          <span className="num">Item price</span>
          <span />
        </div>
        {rows.map((r, idx) => {
          const item = items.find((i) => i.id === r.item_id);
          return (
            <div className="line-items-row" key={idx}>
              <select value={r.item_id} onChange={(e) => update(idx, { item_id: e.target.value })} aria-label="Item">
                {items.map((i) => (
                  <option key={i.id} value={i.id}>
                    {i.name} ({i.sku})
                  </option>
                ))}
              </select>
              <input type="number" min={0} step="any" value={r.min_qty} onChange={(e) => update(idx, { min_qty: e.target.value })} aria-label="From quantity" />
              <input type="number" min={0} step="any" value={r.unit_price} onChange={(e) => update(idx, { unit_price: e.target.value })} aria-label="Price" />
              <span className="num">{item ? inr(item.unit_price) : "—"}</span>
              <button type="button" className="icon-btn" aria-label="Remove price" onClick={() => setRows(rows.filter((_, i) => i !== idx))}>
                <Icon name="x" size={16} />
              </button>
            </div>
          );
        })}
        <button
          type="button"
          className="ghost-btn sm"
          disabled={items.length === 0}
          onClick={() => setRows([...rows, { item_id: items[0]?.id ?? "", min_qty: "1", unit_price: "" }])}
        >
          <Icon name="plus" size={14} /> Add price
        </button>
        <p className="card-note">Add the same item again with a higher “from qty” for a quantity break.</p>
      </div>
      {error && <div className="error-banner">{error}</div>}
      <div className="form-actions">
        <button className="primary-btn" disabled={!valid || saving} onClick={save}>
          {saving ? "Saving…" : "Save price list"}
        </button>
        <button className="secondary-btn" onClick={onDone}>
          Cancel
        </button>
        {list && (
          <button className="danger-btn" onClick={remove}>
            Delete
          </button>
        )}
      </div>
    </div>
  );
}
