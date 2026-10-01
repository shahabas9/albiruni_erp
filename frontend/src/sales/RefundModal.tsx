import { useState } from "react";
import { ApiError } from "../api/client";
import { createRefund, PAYMENT_MODES, type PaymentMode, type Refund } from "../api/sales";
import { ErrorNote, Modal } from "../crm/ui";
import { inr, todayIso } from "../lib/format";

/** Pay a customer back from one advance payment or one invoice's credit balance. */
export function RefundModal({
  source,
  onClose,
  onDone,
}: {
  source: { receipt_id?: string; invoice_id?: string; number: string; customer_name: string; available: number };
  onClose: () => void;
  onDone: (refund: Refund) => void;
}) {
  const [amount, setAmount] = useState(String(source.available));
  const [mode, setMode] = useState<PaymentMode>("Bank transfer");
  const [reference, setReference] = useState("");
  const [reason, setReason] = useState("");
  const [day, setDay] = useState(todayIso());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const total = Number(amount) || 0;
  const needsRef = mode === "Cheque" || mode === "Bank transfer" || mode === "UPI";
  const valid = total > 0 && total <= source.available + 0.005 && reason.trim() && (!needsRef || reference.trim());

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      onDone(
        await createRefund({
          ...(source.receipt_id ? { receipt_id: source.receipt_id } : { invoice_id: source.invoice_id }),
          amount: total,
          mode,
          reference,
          reason: reason.trim(),
          refund_date: day,
        }),
      );
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't record the refund.");
      setBusy(false);
    }
  }

  return (
    <Modal
      title={`Refund to ${source.customer_name}`}
      onClose={onClose}
      footer={
        <>
          <button className="ghost-btn" onClick={onClose}>
            Cancel
          </button>
          <button className="primary-btn" type="submit" form="refund-form" disabled={busy || !valid}>
            {busy ? "Saving…" : `Refund ${inr(total)}`}
          </button>
        </>
      }
    >
      <ErrorNote message={error} />
      <p className="card-note">
        {inr(source.available)} can be paid back from {source.receipt_id ? "the advance on" : "the credit balance on"} {source.number}.
      </p>
      <form id="refund-form" onSubmit={submit} className="fields">
        <label className="field">
          Amount paid back (₹)
          <input type="number" min={0} max={source.available} step="0.01" value={amount} onChange={(e) => setAmount(e.target.value)} autoFocus />
        </label>
        <label className="field">
          Date
          <input type="date" value={day} max={todayIso()} onChange={(e) => setDay(e.target.value)} />
        </label>
        <label className="field">
          Mode
          <select value={mode} onChange={(e) => setMode(e.target.value as PaymentMode)}>
            {PAYMENT_MODES.map((m) => (
              <option key={m}>{m}</option>
            ))}
          </select>
        </label>
        <label className="field">
          {mode === "Cheque" ? "Cheque no." : needsRef ? "UTR / reference" : "Reference (optional)"}
          <input value={reference} maxLength={60} onChange={(e) => setReference(e.target.value)} />
        </label>
        <label className="field full">
          Reason
          <input value={reason} maxLength={200} placeholder="e.g. Order cancelled, goods returned" onChange={(e) => setReason(e.target.value)} />
        </label>
        {total > source.available + 0.005 && <p className="error-banner full">Only {inr(source.available)} can be refunded.</p>}
      </form>
    </Modal>
  );
}
