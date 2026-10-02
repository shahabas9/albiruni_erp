import { useEffect, useState } from "react";
import type { Item } from "../api/client";
import { fetchAgreedPrices, type AgreedPrices } from "../api/sales";
import { Icon } from "../components/Icon";
import { inr, currencyLabel, moneyCurrency } from "../lib/format";

export interface EditLine {
  item_id: string;
  qty: string;
  /** "" means the customer's agreed price. */
  unit_price: string;
  /** This line's own discount, %. */
  discount_pct: string;
}

export function blankLine(items: Item[]): EditLine {
  return { item_id: items[0]?.id ?? "", qty: "1", unit_price: "", discount_pct: "" };
}

/** A saved line, back into the editor. */
export function editLine(l: { item_id?: string | null; qty: number; unit_price: number; discount_pct?: number }): EditLine {
  return { item_id: l.item_id ?? "", qty: String(l.qty), unit_price: String(l.unit_price), discount_pct: l.discount_pct ? String(l.discount_pct) : "" };
}

/** What the API takes for a line. */
export function linePayload(l: EditLine) {
  return {
    item_id: l.item_id,
    qty: Number(l.qty),
    ...(l.unit_price === "" ? {} : { unit_price: Number(l.unit_price) }),
    ...(Number(l.discount_pct) ? { discount_pct: Number(l.discount_pct) } : {}),
  };
}

/** The price list that applies to this customer (or the company default); {} until loaded. */
export function useAgreedPrices(customerId: string | null | undefined): AgreedPrices {
  const [prices, setPrices] = useState<AgreedPrices>({});
  useEffect(() => {
    let live = true;
    fetchAgreedPrices(customerId || undefined)
      .then((r) => live && setPrices(r.prices))
      .catch(() => live && setPrices({}));
    return () => {
      live = false;
    };
  }, [customerId]);
  return prices;
}

/** The customer's price for this quantity: the highest break not above it, else the item's price. */
export function agreedPrice(item: Item, qty: number, prices: AgreedPrices = {}): number {
  const eligible = (prices[item.id] ?? []).filter((b) => b.min_qty <= qty);
  return eligible.length ? eligible[eligible.length - 1].unit_price : item.unit_price;
}

/** Rough figures while typing; the server works out the exact GST on save. */
export function estimate(lines: EditLine[], items: Item[], discountPct: number, prices: AgreedPrices = {}) {
  const factor = 1 - (discountPct || 0) / 100;
  let taxable = 0;
  let gst = 0;
  for (const l of lines) {
    const item = items.find((i) => i.id === l.item_id);
    if (!item) continue;
    const qty = Number(l.qty) || 0;
    const price = l.unit_price === "" ? agreedPrice(item, qty, prices) : Number(l.unit_price) || 0;
    const value = price * qty * (1 - (Number(l.discount_pct) || 0) / 100) * factor;
    taxable += value;
    gst += (value * (item.gst_rate ?? 0)) / 100;
  }
  // Indian invoices round the total to the rupee; Saudi ones keep halalas.
  const exact = Math.round((taxable + gst) * 100) / 100;
  return { taxable, gst, total: moneyCurrency() === "INR" ? Math.round(exact) : exact };
}

/** Item, quantity, price and discount rows for quotations, orders and counter sales. */
export function LineItemsEditor({
  lines,
  items,
  onChange,
  prices = {},
}: {
  lines: EditLine[];
  items: Item[];
  onChange: (lines: EditLine[]) => void;
  /** The customer's agreed prices; rates left blank use them. */
  prices?: AgreedPrices;
}) {
  const update = (idx: number, patch: Partial<EditLine>) => onChange(lines.map((l, i) => (i === idx ? { ...l, ...patch } : l)));
  if (items.length === 0) return <p className="card-note">No items in the price list yet — add items first.</p>;
  return (
    <div className="line-items">
      <div className="line-items-head">
        <span>Item</span>
        <span>Qty</span>
        <span>Rate ({currencyLabel()}, before tax)</span>
        <span>Disc %</span>
        <span className="num">Amount</span>
        <span />
      </div>
      {lines.map((line, idx) => {
        const item = items.find((i) => i.id === line.item_id);
        const qty = Number(line.qty) || 0;
        const agreed = item ? agreedPrice(item, qty, prices) : 0;
        const price = line.unit_price === "" ? agreed : Number(line.unit_price) || 0;
        const below = item && line.unit_price !== "" && price < agreed;
        const special = item && agreed !== item.unit_price;
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
                placeholder={item ? String(agreed) : ""}
                onChange={(e) => update(idx, { unit_price: e.target.value })}
                aria-label="Rate"
              />
              {below ? (
                <small className="below-list">Below {special ? "agreed price" : "list"} — needs approval</small>
              ) : (
                special && line.unit_price === "" && <small className="card-note">Price list (item {inr(item.unit_price)})</small>
              )}
            </div>
            <input
              type="number"
              min={0}
              max={100}
              step="any"
              value={line.discount_pct}
              placeholder="0"
              onChange={(e) => update(idx, { discount_pct: e.target.value })}
              aria-label="Line discount %"
            />
            <span className="num">{inr(price * qty * (1 - (Number(line.discount_pct) || 0) / 100))}</span>
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
