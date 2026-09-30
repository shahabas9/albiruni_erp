import { useState } from "react";
import { ApiError } from "../api/client";
import { createDelivery, type SalesOrder } from "../api/sales";
import { ErrorNote, Modal } from "../crm/ui";
import { todayIso } from "../lib/format";

/** Deliver some or all of what's left on an order's goods lines. */
export function DeliverModal({ order, goodsLineIds, onClose, onDone }: { order: SalesOrder; goodsLineIds: Set<string>; onClose: () => void; onDone: () => void }) {
  const lines = order.lines.filter((l) => goodsLineIds.has(l.id) && l.qty - l.delivered_qty > 0);
  const [qty, setQty] = useState<Record<string, string>>(() => Object.fromEntries(lines.map((l) => [l.id, String(l.qty - l.delivered_qty)])));
  const [day, setDay] = useState(todayIso());
  const [vehicle, setVehicle] = useState("");
  const [transporter, setTransporter] = useState("");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await createDelivery(order.id, {
        lines: lines.map((l) => ({ order_line_id: l.id, qty: Number(qty[l.id]) || 0 })).filter((l) => l.qty > 0),
        delivery_date: day,
        vehicle_no: vehicle,
        transporter,
        notes,
      });
      onDone();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't record the delivery.");
      setBusy(false);
    }
  }

  return (
    <Modal
      title={`Deliver ${order.number}`}
      wide
      onClose={onClose}
      footer={
        <>
          <button className="ghost-btn" onClick={onClose}>
            Cancel
          </button>
          <button className="primary-btn" type="submit" form="deliver-form" disabled={busy}>
            {busy ? "Saving…" : "Record delivery"}
          </button>
        </>
      }
    >
      <ErrorNote message={error} />
      <form id="deliver-form" onSubmit={submit} className="fields">
        <div className="table-wrap full">
          <table className="doc-lines">
            <thead>
              <tr>
                <th>Item</th>
                <th className="num">Ordered</th>
                <th className="num">Delivered</th>
                <th className="num">Deliver now</th>
              </tr>
            </thead>
            <tbody>
              {lines.map((l) => (
                <tr key={l.id}>
                  <td>{l.description}</td>
                  <td className="num">
                    {l.qty} {l.uom}
                  </td>
                  <td className="num">{l.delivered_qty}</td>
                  <td className="num">
                    <input
                      type="number"
                      min={0}
                      max={l.qty - l.delivered_qty}
                      step="any"
                      value={qty[l.id]}
                      onChange={(e) => setQty({ ...qty, [l.id]: e.target.value })}
                      aria-label={`Deliver ${l.description}`}
                      className="qty-input"
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <label className="field">
          Delivery date
          <input type="date" value={day} onChange={(e) => setDay(e.target.value)} />
        </label>
        <label className="field">
          Vehicle no.
          <input value={vehicle} maxLength={20} onChange={(e) => setVehicle(e.target.value.toUpperCase())} placeholder="KL 11 AB 1234" />
        </label>
        <label className="field full">
          Transporter
          <input value={transporter} maxLength={120} onChange={(e) => setTransporter(e.target.value)} />
        </label>
        <label className="field full">
          Notes
          <input value={notes} onChange={(e) => setNotes(e.target.value)} />
        </label>
      </form>
    </Modal>
  );
}
