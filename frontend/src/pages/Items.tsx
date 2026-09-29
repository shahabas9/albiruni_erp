import { useEffect, useState } from "react";
import { ApiError, createItem, fetchItems, updateItem, type Item } from "../api/client";

export function Items() {
  const [items, setItems] = useState<Item[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);

  async function refresh() {
    setLoading(true);
    try {
      setItems(await fetchItems());
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
        <div className="eyebrow">Inventory</div>
        <h1 className="page-title">Items</h1>
        <p className="page-sub">Products and pricing — the stock and price list Ask ERP checks before drafting a quotation.</p>
      </div>

      {error && <div className="error-banner">{error}</div>}

      <div className="toolbar">
        <div />
        <button className="primary-btn" onClick={() => setShowForm((v) => !v)}>
          {showForm ? "Cancel" : "+ New item"}
        </button>
      </div>

      {showForm && <ItemForm onDone={() => { setShowForm(false); refresh(); }} />}

      {!loading && items.length === 0 && !showForm && (
        <div className="card" style={{ textAlign: "center", color: "var(--ink-dim)" }}>
          No items yet — add one above.
        </div>
      )}

      {items.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>SKU</th>
                <th>Name</th>
                <th>UOM</th>
                <th>Unit price</th>
                <th>Stock</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {items.map((i) =>
                editingId === i.id ? (
                  <tr key={i.id}>
                    <td colSpan={6}>
                      <ItemForm
                        item={i}
                        onDone={() => {
                          setEditingId(null);
                          refresh();
                        }}
                      />
                    </td>
                  </tr>
                ) : (
                  <tr key={i.id}>
                    <td className="mono">{i.sku}</td>
                    <td>{i.name}</td>
                    <td>{i.uom}</td>
                    <td className="mono">₹{i.unit_price.toLocaleString("en-IN")}</td>
                    <td className="mono">{i.stock_qty}</td>
                    <td>
                      <button className="secondary-btn" onClick={() => setEditingId(i.id)}>
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

function ItemForm({ item, onDone }: { item?: Item; onDone: () => void }) {
  const [sku, setSku] = useState(item?.sku ?? "");
  const [name, setName] = useState(item?.name ?? "");
  const [uom, setUom] = useState(item?.uom ?? "box");
  const [unitPrice, setUnitPrice] = useState(String(item?.unit_price ?? 0));
  const [stockQty, setStockQty] = useState(String(item?.stock_qty ?? 0));
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function save() {
    setSaving(true);
    setError(null);
    const body = { sku, name, uom, unit_price: Number(unitPrice), stock_qty: Number(stockQty) };
    try {
      if (item) await updateItem(item.id, body);
      else await createItem(body);
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
          <span>SKU</span>
          <input value={sku} onChange={(e) => setSku(e.target.value)} autoFocus />
        </label>
        <label className="field">
          <span>Name</span>
          <input value={name} onChange={(e) => setName(e.target.value)} />
        </label>
        <label className="field">
          <span>Unit of measure</span>
          <input value={uom} onChange={(e) => setUom(e.target.value)} />
        </label>
        <label className="field">
          <span>Unit price (₹)</span>
          <input type="number" min={0} value={unitPrice} onChange={(e) => setUnitPrice(e.target.value)} />
        </label>
        <label className="field">
          <span>Stock quantity</span>
          <input type="number" min={0} value={stockQty} onChange={(e) => setStockQty(e.target.value)} />
        </label>
      </div>
      {error && <div className="error-banner">{error}</div>}
      <div className="form-actions">
        <button className="primary-btn" disabled={!sku.trim() || !name.trim() || saving} onClick={save}>
          {saving ? "Saving…" : "Save"}
        </button>
        <button className="secondary-btn" onClick={onDone}>
          Cancel
        </button>
      </div>
    </div>
  );
}
