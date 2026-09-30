import type { Item } from "../api/client";
import { Icon } from "../components/Icon";
import { inr } from "../lib/format";

export interface EditLine {
  item_id: string;
  qty: string;
  /** "" means the item's list price. */
  unit_price: string;
}

export function blankLine(items: Item[]): EditLine {
  return { item_id: items[0]?.id ?? "", qty: "1", unit_price: "" };
}

/** Rough figures while typing; the server works out the exact GST on save. */
export function estimate(lines: EditLine[], items: Item[], discountPct: number) {
  const factor = 1 - (discountPct || 0) / 100;
  let taxable = 0;
  let gst = 0;
  for (const l of lines) {
    const item = items.find((i) => i.id === l.item_id);
    if (!item) continue;
    const price = l.unit_price === "" ? item.unit_price : Number(l.unit_price) || 0;
    const value = price * (Number(l.qty) || 0) * factor;
    taxable += value;
    gst += (value * (item.gst_rate ?? 0)) / 100;
  }
  return { taxable, gst, total: Math.round(taxable + gst) };
}

/** Item, quantity and price rows for orders (and anything else priced per line). */
export function LineItemsEditor({ lines, items, onChange }: { lines: EditLine[]; items: Item[]; onChange: (lines: EditLine[]) => void }) {
  const update = (idx: number, patch: Partial<EditLine>) => onChange(lines.map((l, i) => (i === idx ? { ...l, ...patch } : l)));
  if (items.length === 0) return <p className="card-note">No items in the price list yet — add items first.</p>;
  return (
    <div className="line-items">
      <div className="line-items-head">
        <span>Item</span>
        <span>Qty</span>
        <span>Rate (₹, before GST)</span>
        <span className="num">Amount</span>
        <span />
      </div>
      {lines.map((line, idx) => {
        const item = items.find((i) => i.id === line.item_id);
        const price = line.unit_price === "" ? (item?.unit_price ?? 0) : Number(line.unit_price) || 0;
        const below = item && line.unit_price !== "" && price < item.unit_price;
        return (
          <div className="line-items-row" key={idx}>
            <select value={line.item_id} onChange={(e) => update(idx, { item_id: e.target.value, unit_price: "" })} aria-label="Item">
              {items.map((i) => (
                <option key={i.id} value={i.id}>
                  {i.name} · {inr(i.unit_price)}/{i.uom}
                  {i.gst_rate === null ? " · no GST rate" : ` · GST ${i.gst_rate}%`}
                  {i.kind === "goods" ? ` · ${i.stock_qty} in stock` : ""}
                </option>
              ))}
            </select>
            <input type="number" min={0} step="any" value={line.qty} onChange={(e) => update(idx, { qty: e.target.value })} aria-label="Quantity" />
            <div className="rate-cell">
              <input
                type="number"
                min={0}
                step="any"
                value={line.unit_price}
                placeholder={item ? String(item.unit_price) : ""}
                onChange={(e) => update(idx, { unit_price: e.target.value })}
                aria-label="Rate"
              />
              {below && <small className="below-list">Below list — needs approval</small>}
            </div>
            <span className="num">{inr(price * (Number(line.qty) || 0))}</span>
            <button
              type="button"
              className="icon-btn"
              aria-label="Remove line"
              disabled={lines.length === 1}
              onClick={() => onChange(lines.filter((_, i) => i !== idx))}
            >
              <Icon name="x" size={16} />
            </button>
          </div>
        );
      })}
      <button type="button" className="ghost-btn sm" onClick={() => onChange([...lines, blankLine(items)])}>
        <Icon name="plus" size={14} /> Add line
      </button>
    </div>
  );
}
