import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, type Item } from "../api/client";
import { adjustStock, fetchStockLedger, type StockMovement } from "../api/sales";
import { Drawer, ErrorNote } from "../crm/ui";
import { dateTime } from "../lib/format";

/** An item's stock ledger, and a stock count for people allowed to adjust. */
export function StockDrawer({ item, canAdjust, onClose, onChanged }: { item: Item; canAdjust: boolean; onClose: () => void; onChanged: () => void }) {
  const [rows, setRows] = useState<StockMovement[] | null>(null);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [counted, setCounted] = useState(String(item.stock_qty));
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [version, setVersion] = useState(0);

  useEffect(() => {
    let live = true;
    fetchStockLedger(item.id, 100)
      .then((page) => live && (setRows(page.rows), setTotal(page.total)))
      .catch((err) => live && setError(err instanceof ApiError ? err.message : "Couldn't load the stock ledger."));
    return () => {
      live = false;
    };
  }, [item.id, version]);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await adjustStock(item.id, Number(counted), reason);
      setReason("");
      setVersion((v) => v + 1);
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't adjust the stock.");
    } finally {
      setBusy(false);
    }
  }

  const link = (m: StockMovement) =>
    m.ref_type === "delivery_note" ? <span className="mono">{m.ref_number}</span> : m.ref_number ? <span className="mono">{m.ref_number}</span> : null;

  return (
    <Drawer title={item.name} subtitle={`${item.sku} · ${item.stock_qty} ${item.uom} in stock`} onClose={onClose}>
      <ErrorNote message={error} />
      {canAdjust && (
        <form className="card form-card" onSubmit={save}>
          <div className="card-title">Stock count</div>
          <div className="field-grid">
            <label className="field">
              <span>Counted quantity</span>
              <input type="number" min={0} step="any" value={counted} onChange={(e) => setCounted(e.target.value)} />
            </label>
            <label className="field">
              <span>Reason</span>
              <input value={reason} maxLength={200} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Count 30 Sep, Damaged" />
            </label>
          </div>
          <div className="form-actions">
            <button className="primary-btn" disabled={busy || !reason.trim() || Number(counted) === item.stock_qty}>
              {busy ? "Saving…" : "Adjust stock"}
            </button>
          </div>
        </form>
      )}
      <div className="card-title" style={{ margin: "8px 0" }}>
        Stock ledger {total > 100 && <small className="card-note">(latest 100 of {total})</small>}
      </div>
      {rows === null ? (
        <p className="card-note">Loading…</p>
      ) : rows.length === 0 ? (
        <p className="card-note">No stock movements yet.</p>
      ) : (
        <div className="table-wrap">
          <table className="doc-lines">
            <thead>
              <tr>
                <th>When</th>
                <th>What</th>
                <th className="num">Change</th>
                <th className="num">Balance</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((m) => (
                <tr key={m.id}>
                  <td>
                    {dateTime(m.created_at)}
                    {m.created_by_name && <small>{m.created_by_name}</small>}
                  </td>
                  <td>
                    {m.kind} {link(m)}
                    {m.note && <small>{m.note}</small>}
                  </td>
                  <td className={`num ${m.qty < 0 ? "qty-out" : "qty-in"}`}>{m.qty > 0 ? `+${m.qty}` : m.qty}</td>
                  <td className="num">{m.balance_after}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="card-note">
        Deliveries are recorded from <Link to="/sales/deliveries">Sales → Deliveries</Link>.
      </p>
    </Drawer>
  );
}
