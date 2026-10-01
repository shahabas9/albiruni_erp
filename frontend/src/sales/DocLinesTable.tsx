import type { DocLine } from "../api/sales";
import { inr } from "../lib/format";

/** A document's lines with tax, and optionally how much was delivered and invoiced. */
export function DocLinesTable({ lines, progress = false }: { lines: DocLine[]; progress?: boolean }) {
  return (
    <div className="table-wrap">
      <table className="doc-lines">
        <thead>
          <tr>
            <th>Item</th>
            <th>HSN/SAC</th>
            <th className="num">Qty</th>
            <th className="num">Rate</th>
            <th className="num">GST</th>
            <th className="num">Taxable</th>
            <th className="num">Tax</th>
            {progress && <th className="num">Delivered</th>}
            {progress && <th className="num">Invoiced</th>}
          </tr>
        </thead>
        <tbody>
          {lines.map((l) => (
            <tr key={l.id}>
              <td>
                {l.description}
                {l.unit_price < l.list_price && <small className="below-list">List {inr(l.list_price)}</small>}
              </td>
              <td className="mono">{l.hsn_code || "—"}</td>
              <td className="num">
                {l.qty} {l.uom}
              </td>
              <td className="num">
                {inr(l.unit_price)}
                {l.discount_pct > 0 && <small className="card-note"> less {l.discount_pct}%</small>}
              </td>
              <td className="num">{l.gst_rate}%</td>
              <td className="num">{inr(l.taxable_value)}</td>
              <td className="num">{inr(l.cgst + l.sgst + l.igst)}</td>
              {progress && <td className="num">{l.delivered_qty}</td>}
              {progress && <td className="num">{l.invoiced_qty}</td>}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
