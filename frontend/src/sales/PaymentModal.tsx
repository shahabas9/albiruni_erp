import { useEffect, useState } from "react";
import { ApiError } from "../api/client";
import { fetchInvoices, PAYMENT_MODES, recordPayment, TDS_SECTIONS, type Invoice, type PaymentMode, type Receipt } from "../api/sales";
import { CustomerPicker } from "../components/CustomerPicker";
import { ErrorNote, Modal } from "../crm/ui";
import { dayDate, inr, todayIso, currencyLabel, taxLabel } from "../lib/format";

/** Record money received and say which invoices it pays. */
export function PaymentModal({
  customer,
  invoice,
  onClose,
  onDone,
}: {
  /** Fixed customer (e.g. from an invoice); otherwise picked here. */
  customer?: { id: string; name: string };
  /** Pre-fill the amount with this invoice's balance and apply it there. */
  invoice?: Invoice;
  onClose: () => void;
  onDone: (receipt: Receipt) => void;
}) {
  const [customerId, setCustomerId] = useState(customer?.id ?? "");
  const [amount, setAmount] = useState(invoice ? String(invoice.balance) : "");
  const [mode, setMode] = useState<PaymentMode>("UPI");
  const [reference, setReference] = useState("");
  const [day, setDay] = useState(todayIso());
  const [notes, setNotes] = useState("");
  const [open, setOpen] = useState<Invoice[]>([]);
  const [manual, setManual] = useState(Boolean(invoice));
  const [alloc, setAlloc] = useState<Record<string, string>>(invoice ? { [invoice.id]: String(invoice.balance) } : {});
  const [withTds, setWithTds] = useState(false);
  const [tds, setTds] = useState<Record<string, string>>({});
  const [section, setSection] = useState("194Q");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!customerId) return;
    let live = true;
    fetchInvoices({ customer_id: customerId, status: "unpaid", limit: 100 })
      .then((page) => live && setOpen([...page.rows].sort((a, b) => a.due_date.localeCompare(b.due_date))))
      .catch(() => live && setOpen([]));
    return () => {
      live = false;
    };
  }, [customerId]);

  const total = Number(amount) || 0;
  const allocatedSum = open.reduce((s, i) => s + (Number(alloc[i.id]) || 0), 0);
  const tdsSum = withTds ? open.reduce((s, i) => s + (Number(tds[i.id]) || 0), 0) : 0;
  const overBalance = open.some((i) => (Number(alloc[i.id]) || 0) + (withTds ? Number(tds[i.id]) || 0 : 0) > i.balance + 0.005);
  const autoPlan = (() => {
    let left = total;
    return open.map((i) => {
      const take = Math.max(0, Math.min(left, i.balance));
      left -= take;
      return take;
    });
  })();
  const advance = manual ? total - allocatedSum : Math.max(0, total - autoPlan.reduce((a, b) => a + b, 0));
  const needsRef = mode === "Cheque" || mode === "Bank transfer" || mode === "UPI";

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const receipt = await recordPayment({
        customer_id: customerId,
        amount: total,
        mode,
        reference,
        notes,
        receipt_date: day,
        ...(manual
          ? {
              allocations: open
                .filter((i) => Number(alloc[i.id]) > 0 || (withTds && Number(tds[i.id]) > 0))
                .map((i) => ({ invoice_id: i.id, amount: Number(alloc[i.id]) || 0, tds_amount: withTds ? Number(tds[i.id]) || 0 : 0 })),
              ...(withTds ? { tds_section: section } : {}),
            }
          : {}),
      });
      onDone(receipt);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't record the payment.");
      setBusy(false);
    }
  }

  return (
    <Modal
      title={customer ? `Payment from ${customer.name}` : "Record a payment"}
      wide
      onClose={onClose}
      footer={
        <>
          <button className="ghost-btn" onClick={onClose}>
            Cancel
          </button>
          <button className="primary-btn" type="submit" form="payment-form" disabled={busy || !customerId || total <= 0 || advance < -0.005 || overBalance || (needsRef && !reference.trim())}>
            {busy ? "Saving…" : `Record ${inr(total)}`}
          </button>
        </>
      }
    >
      <ErrorNote message={error} />
      <form id="payment-form" onSubmit={submit} className="fields">
        {!customer && (
          <div className="full">
            <CustomerPicker value={customerId} onChange={(id) => (setCustomerId(id), setAlloc({}))} />
          </div>
        )}
        <label className="field">
          Amount received ({currencyLabel()})
          <input
            type="number"
            min={0}
            step="0.01"
            value={amount}
            onChange={(e) => {
              setAmount(e.target.value);
              // Paying one invoice: the amount applied to it follows what was received (up to its balance).
              if (invoice && manual) setAlloc({ [invoice.id]: String(Math.min(Number(e.target.value) || 0, invoice.balance)) });
            }}
            autoFocus
          />
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
        {mode === "Cash" && total >= 200000 && currencyLabel() === "₹" && <p className="error-banner full">Cash receipts of ₹2,00,000 or more aren't allowed (section 269ST).</p>}

        <div className="field full">
          Apply to
          <div className="filters">
            <button type="button" className={!manual ? "on" : ""} onClick={() => setManual(false)}>
              Oldest invoices first
            </button>
            <button type="button" className={manual ? "on" : ""} onClick={() => setManual(true)}>
              Choose invoices
            </button>
          </div>
        </div>
        {taxLabel() === "GST" && (
          <label className="field checkbox-field">
            <input type="checkbox" checked={withTds} onChange={(e) => (setWithTds(e.target.checked), e.target.checked && setManual(true))} />
            <span>Customer deducted TDS</span>
          </label>
        )}
        {withTds && (
          <label className="field">
            TDS section
            <select value={section} onChange={(e) => setSection(e.target.value)}>
              {TDS_SECTIONS.map((s) => (
                <option key={s}>{s}</option>
              ))}
            </select>
          </label>
        )}
        {customerId && open.length === 0 && <p className="card-note full">No unpaid invoices — the whole amount is kept as an advance.</p>}
        {open.length > 0 && (
          <div className="table-wrap full">
            <table className="doc-lines">
              <thead>
                <tr>
                  <th>Invoice</th>
                  <th>Due</th>
                  <th className="num">Balance</th>
                  <th className="num">Apply</th>
                  {withTds && <th className="num">TDS deducted</th>}
                </tr>
              </thead>
              <tbody>
                {open.map((i, idx) => (
                  <tr key={i.id}>
                    <td className="mono">{i.number}</td>
                    <td>
                      {dayDate(i.due_date)}
                      {i.payment_status === "Overdue" && <small className="below-list">Overdue</small>}
                    </td>
                    <td className="num">{inr(i.balance)}</td>
                    <td className="num">
                      {manual ? (
                        <input
                          type="number"
                          min={0}
                          max={i.balance}
                          step="0.01"
                          className="qty-input"
                          value={alloc[i.id] ?? ""}
                          placeholder="0"
                          onChange={(e) => setAlloc({ ...alloc, [i.id]: e.target.value })}
                          aria-label={`Apply to ${i.number}`}
                        />
                      ) : (
                        inr(autoPlan[idx] ?? 0)
                      )}
                    </td>
                    {withTds && (
                      <td className="num">
                        <input
                          type="number"
                          min={0}
                          step="0.01"
                          className="qty-input"
                          value={tds[i.id] ?? ""}
                          placeholder="0"
                          onChange={(e) => setTds({ ...tds, [i.id]: e.target.value })}
                          aria-label={`TDS on ${i.number}`}
                        />
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {overBalance && <p className="error-banner full">What's applied plus TDS is more than an invoice's balance.</p>}
        {tdsSum > 0 && <p className="card-note full">{inr(tdsSum)} TDS settles the rest of those invoices; chase the customer's Form 16A for it.</p>}
        <p className={`full ${advance < -0.005 ? "error-banner" : "card-note"}`}>
          {advance < -0.005
            ? `That's ${inr(-advance)} more than was received.`
            : advance > 0.005
              ? `${inr(advance)} will be kept as an advance for later invoices.`
              : "All of it goes against invoices."}
        </p>
        <label className="field full">
          Notes
          <input value={notes} onChange={(e) => setNotes(e.target.value)} />
        </label>
      </form>
    </Modal>
  );
}
