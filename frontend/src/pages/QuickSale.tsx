import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError, fetchSalesItems, type Item } from "../api/client";
import { PAYMENT_MODES, quickSale, type PaymentMode } from "../api/sales";
import { CustomerPicker } from "../components/CustomerPicker";
import { ErrorNote } from "../crm/ui";
import { useAppData } from "../data/AppDataProvider";
import { inr } from "../lib/format";
import { blankLine, estimate, LineItemsEditor, type EditLine } from "../sales/LineItemsEditor";

/** A counter sale: pick items, take the money, print the invoice. */
export function QuickSale() {
  const navigate = useNavigate();
  const { can } = useAppData();
  const [items, setItems] = useState<Item[] | null>(null);
  const [walkIn, setWalkIn] = useState(true);
  const [customerId, setCustomerId] = useState("");
  const [lines, setLines] = useState<EditLine[]>([]);
  const [discount, setDiscount] = useState("0");
  const [paidNow, setPaidNow] = useState(true);
  const [mode, setMode] = useState<PaymentMode>("Cash");
  const [reference, setReference] = useState("");
  const [received, setReceived] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchSalesItems()
      .then((its) => (setItems(its), setLines([blankLine(its)])))
      .catch((err) => setError(err instanceof ApiError ? err.message : "Couldn't load items."));
  }, []);

  if (!items) return <section>{error ? <ErrorNote message={error} /> : <p className="card-note">Loading…</p>}</section>;

  const est = estimate(lines, items, Number(discount));
  const tendered = received === "" ? est.total : Number(received) || 0;
  const change = paidNow && mode === "Cash" ? tendered - est.total : 0;
  const needsRef = paidNow && (mode === "UPI" || mode === "Bank transfer" || mode === "Cheque");
  const canPay = can("sales.payment.write");
  const valid = (walkIn || customerId) && lines.length > 0 && lines.every((l) => l.item_id && Number(l.qty) > 0) && (!needsRef || reference.trim());

  async function complete() {
    setBusy(true);
    setError(null);
    try {
      const out = await quickSale({
        ...(walkIn ? {} : { customer_id: customerId }),
        lines: lines.map((l) => ({ item_id: l.item_id, qty: Number(l.qty), ...(l.unit_price === "" ? {} : { unit_price: Number(l.unit_price) }) })),
        discount_pct: Number(discount) || 0,
        notes: "",
        // The bill can only be settled up to its own total; cash change is handed back, not recorded.
        ...(paidNow && canPay ? { payment: { amount: Math.min(tendered, est.total), mode, reference } } : {}),
      });
      window.open(`/print/invoice/${out.invoice_id}`, "_blank", "noopener");
      navigate(`/sales/invoices/${out.invoice_id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't complete the sale.");
      setBusy(false);
    }
  }

  return (
    <section>
      <div className="page-head">
        <div className="eyebrow">Sales</div>
        <h1 className="page-title">Quick sale</h1>
        <p className="page-sub">A counter sale in one step: the order, delivery, tax invoice and payment are all recorded together — or nothing is, if anything's refused.</p>
      </div>
      <div className="card form-card">
        <div className="field full">
          <span>Customer</span>
          <div className="filters">
            <button type="button" className={walkIn ? "on" : ""} onClick={() => setWalkIn(true)}>
              Walk-in
            </button>
            <button type="button" className={!walkIn ? "on" : ""} onClick={() => setWalkIn(false)}>
              Named customer
            </button>
          </div>
        </div>
        {!walkIn && <CustomerPicker value={customerId} onChange={setCustomerId} />}
        <LineItemsEditor lines={lines} items={items} onChange={setLines} />
        <div className="field-grid">
          <label className="field">
            <span>Discount %</span>
            <input type="number" min={0} max={100} step="0.5" value={discount} onChange={(e) => setDiscount(e.target.value)} />
          </label>
        </div>
        <div className="quote-total">
          <span>
            {inr(est.taxable)} + GST {inr(est.gst)} (exact figures on the invoice)
          </span>
          <b className="num">{inr(est.total)}</b>
        </div>
        {canPay && (
          <div className="field-grid">
            <label className="field checkbox-field">
              <input type="checkbox" checked={paidNow} onChange={(e) => setPaidNow(e.target.checked)} />
              <span>Paid now</span>
            </label>
            {paidNow && (
              <>
                <label className="field">
                  <span>Mode</span>
                  <select value={mode} onChange={(e) => setMode(e.target.value as PaymentMode)}>
                    {PAYMENT_MODES.map((m) => (
                      <option key={m}>{m}</option>
                    ))}
                  </select>
                </label>
                {mode === "Cash" ? (
                  <label className="field">
                    <span>Cash received (₹)</span>
                    <input type="number" min={0} step="1" value={received} placeholder={String(est.total)} onChange={(e) => setReceived(e.target.value)} />
                  </label>
                ) : (
                  <label className="field">
                    <span>{mode === "Cheque" ? "Cheque no." : "UTR / reference"}</span>
                    <input value={reference} maxLength={60} onChange={(e) => setReference(e.target.value)} />
                  </label>
                )}
              </>
            )}
          </div>
        )}
        {change > 0 && <div className="notice-banner">Give back {inr(change)} change.</div>}
        {paidNow && mode === "Cash" && tendered < est.total && tendered > 0 && (
          <div className="notice-banner">{inr(est.total - tendered)} will stay owed on the invoice.</div>
        )}
        <ErrorNote message={error} />
        <div className="form-actions">
          <button className="primary-btn" disabled={!valid || busy} onClick={complete}>
            {busy ? "Saving…" : `Complete sale · ${inr(est.total)}`}
          </button>
        </div>
        <p className="card-note">The invoice opens for printing. Big discounts still need a manager; stock and credit limits still apply.</p>
      </div>
    </section>
  );
}
