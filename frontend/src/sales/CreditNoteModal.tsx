import { useState } from "react";
import { ApiError } from "../api/client";
import { createCreditNote, type CreditNote, type Invoice } from "../api/sales";
import { ErrorNote, Modal } from "../crm/ui";
import { inr, todayIso } from "../lib/format";

/** Take back part of an issued invoice: returned goods, or a lower price. */
export function CreditNoteModal({ invoice, onClose, onDone }: { invoice: Invoice; onClose: () => void; onDone: (note: CreditNote) => void }) {
  const [kind, setKind] = useState<CreditNote["kind"]>("Return");
  const [reason, setReason] = useState("");
  const [restock, setRestock] = useState(true);
  const [day, setDay] = useState(todayIso());
  const [values, setValues] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const isReturn = kind === "Return";
  const lines = invoice.lines.filter((l) => (isReturn ? l.qty - l.credited_qty > 0 : l.taxable_value - l.credited_value > 0));

  const estimate = lines.reduce((sum, l) => {
    const v = Number(values[l.id]) || 0;
    const taxable = isReturn ? (l.taxable_value / l.qty) * v : v;
    return sum + taxable * (1 + l.gst_rate / 100);
  }, 0);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const note = await createCreditNote(invoice.id, {
        kind,
        reason,
        restock: isReturn && restock,
        note_date: day,
        lines: lines
          .filter((l) => Number(values[l.id]) > 0)
          .map((l) => (isReturn ? { invoice_line_id: l.id, qty: Number(values[l.id]) } : { invoice_line_id: l.id, amount: Number(values[l.id]) })),
      });
      onDone(note);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't issue the credit note.");
      setBusy(false);
    }
  }

  return (
    <Modal
      title={`Credit note against ${invoice.number}`}
      wide
      onClose={onClose}
      footer={
        <>
          <button className="ghost-btn" onClick={onClose}>
            Cancel
          </button>
          <button className="primary-btn" type="submit" form="credit-form" disabled={busy || !reason.trim() || estimate <= 0}>
            {busy ? "Issuing…" : `Issue credit note (≈ ${inr(Math.round(estimate))})`}
          </button>
        </>
      }
    >
      <ErrorNote message={error} />
      <form id="credit-form" onSubmit={submit} className="fields">
        <div className="field full">
          What happened?
          <div className="filters">
            {(["Return", "Price correction"] as const).map((k) => (
              <button type="button" key={k} className={kind === k ? "on" : ""} onClick={() => (setKind(k), setValues({}))}>
                {k === "Return" ? "Goods returned" : "Price corrected"}
              </button>
            ))}
          </div>
        </div>
        <div className="table-wrap full">
          <table className="doc-lines">
            <thead>
              <tr>
                <th>Item</th>
                <th className="num">{isReturn ? "Invoiced" : "Taxable value"}</th>
                <th className="num">{isReturn ? "Already returned" : "Already credited"}</th>
                <th className="num">{isReturn ? "Returned now" : "Reduce by (₹, before GST)"}</th>
              </tr>
            </thead>
            <tbody>
              {lines.map((l) => (
                <tr key={l.id}>
                  <td>{l.description}</td>
                  <td className="num">{isReturn ? `${l.qty} ${l.uom}` : inr(l.taxable_value)}</td>
                  <td className="num">{isReturn ? l.credited_qty : inr(l.credited_value)}</td>
                  <td className="num">
                    <input
                      type="number"
                      min={0}
                      step="any"
                      max={isReturn ? l.qty - l.credited_qty : l.taxable_value - l.credited_value}
                      className="qty-input"
                      value={values[l.id] ?? ""}
                      placeholder="0"
                      onChange={(e) => setValues({ ...values, [l.id]: e.target.value })}
                      aria-label={`${isReturn ? "Return" : "Reduce"} ${l.description}`}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <label className="field full">
          Reason (printed on the credit note)
          <input value={reason} maxLength={200} onChange={(e) => setReason(e.target.value)} placeholder={isReturn ? "e.g. 3 boxes damaged in transit" : "e.g. Agreed rate was ₹400"} />
        </label>
        <label className="field">
          Date
          <input type="date" value={day} min={invoice.invoice_date} max={todayIso()} onChange={(e) => setDay(e.target.value)} />
        </label>
        {isReturn && (
          <label className="field checkbox-field">
            <input type="checkbox" checked={restock} onChange={(e) => setRestock(e.target.checked)} />
            <span>Put the returned goods back into stock</span>
          </label>
        )}
        <p className="card-note full">Issued straight away with its own number (CN/…). GST is credited at each line's rate.</p>
      </form>
    </Modal>
  );
}
