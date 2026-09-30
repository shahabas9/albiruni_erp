import type { TaxTotals } from "../api/client";
import { inr } from "../lib/format";

/** Subtotal → discount → taxable value → GST → round off → grand total. */
export function DocTotals({ doc, subtotal, discountPct }: { doc: TaxTotals; subtotal?: number; discountPct?: number }) {
  const rows: [string, number][] = [];
  if (subtotal !== undefined && discountPct) {
    rows.push(["Subtotal", subtotal], [`Discount ${discountPct}%`, -(subtotal - doc.total)]);
  }
  rows.push(["Taxable value", doc.total]);
  if (doc.igst) rows.push(["IGST", doc.igst]);
  if (doc.cgst || doc.sgst || !doc.igst) rows.push(["CGST", doc.cgst], ["SGST", doc.sgst]);
  if (doc.round_off) rows.push(["Round off", doc.round_off]);
  return (
    <dl className="doc-totals">
      {rows.map(([label, value]) => (
        <div key={label}>
          <dt>{label}</dt>
          <dd className="num">{value < 0 ? `−${inr(-value)}` : inr(value)}</dd>
        </div>
      ))}
      <div className="grand">
        <dt>Total</dt>
        <dd className="num">{inr(doc.grand_total)}</dd>
      </div>
    </dl>
  );
}
