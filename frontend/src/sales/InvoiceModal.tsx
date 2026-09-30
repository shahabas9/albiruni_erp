import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError } from "../api/client";
import { createInvoiceDraft, type DocLine, type SalesOrder } from "../api/sales";
import { ErrorNote, Modal } from "../crm/ui";

/** Same default as the server: delivered-not-invoiced goods (or everything
 * not invoiced before any delivery), and everything not invoiced for services. */
function defaultQty(l: DocLine): number {
  const left = l.qty - l.invoiced_qty;
  if (l.item_kind === "service") return left;
  const deliveredLeft = l.delivered_qty - l.invoiced_qty;
  return deliveredLeft > 0 ? deliveredLeft : l.delivered_qty === 0 ? left : 0;
}

/** Choose how much of an order to put on a draft invoice. */
export function InvoiceModal({ order, onClose }: { order: SalesOrder; onClose: () => void }) {
  const navigate = useNavigate();
  const lines = order.lines.filter((l) => l.qty - l.invoiced_qty > 0);
  const [qty, setQty] = useState<Record<string, string>>(() => Object.fromEntries(lines.map((l) => [l.id, String(defaultQty(l))])));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const invoice = await createInvoiceDraft(
        order.id,
        lines.map((l) => ({ order_line_id: l.id, qty: Number(qty[l.id]) || 0 })).filter((l) => l.qty > 0),
      );
      navigate(`/sales/invoices/${invoice.id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't make the invoice.");
      setBusy(false);
    }
  }

  return (
    <Modal
      title={`Invoice ${order.number}`}
      wide
      onClose={onClose}
      footer={
        <>
          <button className="ghost-btn" onClick={onClose}>
            Cancel
          </button>
          <button className="primary-btn" type="submit" form="invoice-form" disabled={busy}>
            {busy ? "Saving…" : "Make draft invoice"}
          </button>
        </>
      }
    >
      <ErrorNote message={error} />
      <form id="invoice-form" onSubmit={submit} className="fields">
        <p className="card-note full">A draft has no number yet. Check it, then issue it from the invoice page.</p>
        <div className="table-wrap full">
          <table className="doc-lines">
            <thead>
              <tr>
                <th>Item</th>
                <th className="num">Ordered</th>
                <th className="num">Delivered</th>
                <th className="num">Invoiced</th>
                <th className="num">Invoice now</th>
              </tr>
            </thead>
            <tbody>
              {lines.map((l) => (
                <tr key={l.id}>
                  <td>{l.description}</td>
                  <td className="num">
                    {l.qty} {l.uom}
                  </td>
                  <td className="num">{l.item_kind === "service" ? "—" : l.delivered_qty}</td>
                  <td className="num">{l.invoiced_qty}</td>
                  <td className="num">
                    <input
                      type="number"
                      min={0}
                      max={l.qty - l.invoiced_qty}
                      step="any"
                      className="qty-input"
                      value={qty[l.id]}
                      onChange={(e) => setQty({ ...qty, [l.id]: e.target.value })}
                      aria-label={`Invoice ${l.description}`}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </form>
    </Modal>
  );
}
