import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ApiError } from "../api/client";
import {
  deleteInvoice,
  fetchCreditNotes,
  fetchInvoice,
  fetchInvoiceTimeline,
  issueInvoice,
  type CreditNote,
  type Invoice,
  setInvoiceSalesperson,
} from "../api/sales";
import { SalespersonField } from "../sales/SalespersonField";
import { Timeline } from "../crm/Timeline";
import { ErrorNote } from "../crm/ui";
import { useAppData } from "../data/AppDataProvider";
import { dateTime, dayDate, docStatusClass, inr, todayIso, taxLabel } from "../lib/format";
import { CreditNoteModal } from "../sales/CreditNoteModal";
import { PaymentModal } from "../sales/PaymentModal";
import { RefundModal } from "../sales/RefundModal";
import { GstPortalModal } from "../sales/GstPortalModal";
import { SendModal } from "../sales/SendModal";
import { DocTotals } from "../sales/DocTotals";

export function InvoicePage() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const { can } = useAppData();
  const [invoice, setInvoice] = useState<Invoice | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [changes, setChanges] = useState(0);
  const [issueDate, setIssueDate] = useState(todayIso());
  const [notes, setNotes] = useState<CreditNote[]>([]);
  const [crediting, setCrediting] = useState(false);
  const [refunding, setRefunding] = useState(false);
  const [portal, setPortal] = useState(false);
  const [paying, setPaying] = useState(false);
  const [sending, setSending] = useState<{ kind: "invoice" | "credit_note"; id: string; title: string; reminder?: boolean } | null>(null);

  const load = useCallback(async () => {
    try {
      const [inv, cn] = await Promise.all([fetchInvoice(id), fetchCreditNotes({ invoice_id: id, limit: 100 })]);
      setInvoice(inv);
      setNotes(cn.rows);
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't load this invoice.");
    }
  }, [id]);

  useEffect(() => {
    void load();
  }, [load, changes]);

  if (!invoice) {
    return (
      <section>
        <Link to="/sales/invoices" className="back-link">
          ← Invoices
        </Link>
        <ErrorNote message={error} />
        {!error && <p className="card-note">Loading…</p>}
      </section>
    );
  }

  const canWrite = can("sales.invoice.write");
  const draft = invoice.status === "Draft";

  async function act(fn: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
      setChanges((n) => n + 1);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't do that.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section>
      <Link to="/sales/invoices" className="back-link">
        ← Invoices
      </Link>
      <div className="page-head">
        <div>
          <div className="eyebrow">Tax invoice</div>
          <h1 className="page-title mono">{invoice.number ?? "Draft invoice"}</h1>
          <p className="page-sub">
            <span className={`badge ${docStatusClass(invoice.payment_status)}`}>{invoice.payment_status}</span>{" "}
            <Link to={`/customers/${invoice.customer_id}`}>{invoice.customer_name}</Link> · order{" "}
            <Link to={`/sales/orders/${invoice.order_id}`}>{invoice.order_number}</Link>
            {!draft && ` · ${dayDate(invoice.invoice_date)} · due ${dayDate(invoice.due_date)}`}
          </p>
        </div>
        <div className="head-actions">
          {!draft && (
            <a className="ghost-btn" href={`/print/invoice/${invoice.id}`} target="_blank" rel="noreferrer">
              Print / PDF
            </a>
          )}
          {!draft && (
            <button className="ghost-btn" onClick={() => setSending({ kind: "invoice", id: invoice.id, title: `invoice ${invoice.number}` })}>
              Send
            </button>
          )}
          {!draft && invoice.balance > 0 && (
            <button className="ghost-btn" onClick={() => setSending({ kind: "invoice", id: invoice.id, title: `invoice ${invoice.number}`, reminder: true })}>
              Send reminder
            </button>
          )}
          {!draft && can("sales.payment.write") && invoice.balance > 0 && (
            <button className="primary-btn" onClick={() => setPaying(true)}>
              Record payment
            </button>
          )}
          {!draft && (
            <button className="ghost-btn" onClick={() => setPortal(true)}>
              {invoice.invoice_kind ? "ZATCA e-invoice" : "e-Invoice / e-Way bill"}
            </button>
          )}
          {!draft && can("sales.payment.write") && invoice.balance < 0 && (
            <button className="primary-btn" onClick={() => setRefunding(true)}>
              Refund {inr(-invoice.balance)}
            </button>
          )}
          {!draft && can("sales.credit_note.write") && invoice.amount_credited < invoice.grand_total && (
            <button className="ghost-btn" onClick={() => setCrediting(true)}>
              Credit note
            </button>
          )}
          {draft && canWrite && (
            <>
              <button
                className="ghost-btn"
                disabled={busy}
                onClick={() => window.confirm("Delete this draft invoice?") && act(async () => (await deleteInvoice(invoice.id), navigate(`/sales/orders/${invoice.order_id}`)))}
              >
                Delete draft
              </button>
              <label className="inline-date">
                Invoice date
                <input type="date" value={issueDate} max={todayIso()} onChange={(e) => setIssueDate(e.target.value)} />
              </label>
              <button className="primary-btn" disabled={busy} onClick={() => act(() => issueInvoice(invoice.id, issueDate))}>
                {busy ? "Working…" : "Issue invoice"}
              </button>
            </>
          )}
        </div>
      </div>

      <ErrorNote message={error} />
      {draft && <div className="notice-banner">Draft — not numbered and not owed yet. Issuing numbers it and locks it; mistakes after that need a credit note.</div>}

      <div className="doc-grid">
        <div className="card">
          <div className="table-wrap">
            <table className="doc-lines">
              <thead>
                <tr>
                  <th>Item</th>
                  <th>HSN/SAC</th>
                  <th className="num">Qty</th>
                  <th className="num">Rate</th>
                  <th className="num">{taxLabel()}</th>
                  <th className="num">Taxable</th>
                  <th className="num">Tax</th>
                </tr>
              </thead>
              <tbody>
                {invoice.lines.map((l) => (
                  <tr key={l.id}>
                    <td>
                      {l.description}
                      {l.credited_qty > 0 && <small className="below-list">{l.credited_qty} credited back</small>}
                    </td>
                    <td className="mono">{l.hsn_code || "—"}</td>
                    <td className="num">
                      {l.qty} {l.uom}
                    </td>
                    <td className="num">{inr(l.unit_price)}</td>
                    <td className="num">{l.gst_rate}%</td>
                    <td className="num">{inr(l.taxable_value)}</td>
                    <td className="num">{inr(l.cgst + l.sgst + l.igst + (l.vat ?? 0))}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <DocTotals doc={invoice} subtotal={invoice.subtotal} discountPct={invoice.discount_pct} />
          <p className="card-note" style={{ textAlign: "right" }}>
            {invoice.amount_in_words}
          </p>
          {!draft && (
            <dl className="doc-totals">
              <div>
                <dt>Paid</dt>
                <dd className="num">{inr(invoice.amount_paid)}</dd>
              </div>
              {invoice.amount_tds > 0 && (
                <div>
                  <dt>TDS deducted by customer</dt>
                  <dd className="num">{inr(invoice.amount_tds)}</dd>
                </div>
              )}
              {invoice.amount_credited > 0 && (
                <div>
                  <dt>Credited</dt>
                  <dd className="num">{inr(invoice.amount_credited)}</dd>
                </div>
              )}
              {invoice.amount_refunded > 0 && (
                <div>
                  <dt>Refunded to customer</dt>
                  <dd className="num">{inr(invoice.amount_refunded)}</dd>
                </div>
              )}
              <div className="grand">
                <dt>{invoice.balance < 0 ? "We owe the customer" : "Balance due"}</dt>
                <dd className="num">{inr(Math.abs(invoice.balance))}</dd>
              </div>
            </dl>
          )}
        </div>
        <div>
          <div className="card doc-facts">
            <div>
              <span>Bill to</span>
              <p>
                {invoice.buyer_name}
                {invoice.buyer_vat_number ? (
                  <small className="mono">VAT {invoice.buyer_vat_number}</small>
                ) : invoice.buyer_gstin ? (
                  <small className="mono">GSTIN {invoice.buyer_gstin}</small>
                ) : (
                  <small>{invoice.invoice_kind === "simplified" ? "Simplified tax invoice (B2C)" : "Unregistered"}</small>
                )}
                {invoice.billing_address && <small>{invoice.billing_address}</small>}
              </p>
            </div>
            {taxLabel() === "GST" && (
            <div>
              <span>Place of supply</span>
              <p>
                {invoice.place_of_supply ? `${invoice.place_of_supply} · ${invoice.place_of_supply_name}` : "—"}
              </p>
            </div>
            )}
            {invoice.customer_po && (
              <div>
                <span>Customer PO</span>
                <p>{invoice.customer_po}</p>
              </div>
            )}
            <SalespersonField
              id={invoice.salesperson_id}
              name={invoice.salesperson_name}
              onSave={
                can("sales.invoice.write")
                  ? async (userId) => {
                      await setInvoiceSalesperson(invoice.id, userId);
                      setChanges((n) => n + 1);
                    }
                  : undefined
              }
            />
            {invoice.issued_at && (
              <div>
                <span>Issued</span>
                <p>
                  {dateTime(invoice.issued_at)}
                  {invoice.issued_by_name && ` by ${invoice.issued_by_name}`}
                </p>
              </div>
            )}
          </div>
          {invoice.payments.length > 0 && (
            <div className="card">
              <div className="card-head">
                <span className="card-title">Payments</span>
              </div>
              <div className="mini-docs">
                {invoice.payments.map((p) => (
                  <div className="row" key={p.receipt_id}>
                    <div>
                      <b className="mono">{p.number}</b> · {dayDate(p.receipt_date)}
                      <small>
                        {p.mode}
                        {p.reference && ` ${p.reference}`}
                      </small>
                    </div>
                    <span className="num">
                      {inr(p.amount)}
                      {p.tds_amount > 0 && <small> + {inr(p.tds_amount)} TDS</small>}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
          {notes.length > 0 && (
            <div className="card">
              <div className="card-head">
                <span className="card-title">Credit notes</span>
              </div>
              <div className="mini-docs">
                {notes.map((n) => (
                  <div className="row" key={n.id}>
                    <div>
                      <b className="mono">{n.number}</b> · {dayDate(n.note_date)} · {inr(n.grand_total)}
                      <small>
                        {n.kind}: {n.reason}
                        {n.restocked && " · back in stock"}
                      </small>
                    </div>
                    <div style={{ display: "flex", gap: 6 }}>
                      <button className="ghost-btn sm" onClick={() => setSending({ kind: "credit_note", id: n.id, title: `credit note ${n.number}` })}>
                        Send
                      </button>
                      <a className="ghost-btn sm" href={`/print/credit-note/${n.id}`} target="_blank" rel="noreferrer">
                        Print
                      </a>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
          <div className="card">
            <div className="card-head">
              <span className="card-title">History</span>
            </div>
            <Timeline load={() => fetchInvoiceTimeline(invoice.id)} version={changes} />
          </div>
        </div>
      </div>
      {sending && (
        <SendModal
          kind={sending.kind}
          id={sending.id}
          customerId={invoice.customer_id}
          title={sending.title}
          reminder={sending.reminder}
          onClose={() => setSending(null)}
        />
      )}
      {paying && (
        <PaymentModal
          customer={{ id: invoice.customer_id, name: invoice.customer_name }}
          invoice={invoice}
          onClose={() => setPaying(false)}
          onDone={() => {
            setPaying(false);
            setChanges((n) => n + 1);
          }}
        />
      )}
      {portal && (
        <GstPortalModal
          invoice={invoice}
          canWrite={can("sales.invoice.write")}
          onClose={() => setPortal(false)}
          onSaved={() => {
            setPortal(false);
            setChanges((n) => n + 1);
          }}
        />
      )}
      {refunding && (
        <RefundModal
          source={{ invoice_id: invoice.id, number: invoice.number ?? "", customer_name: invoice.customer_name, available: -invoice.balance }}
          onClose={() => setRefunding(false)}
          onDone={() => {
            setRefunding(false);
            setChanges((n) => n + 1);
          }}
        />
      )}
      {crediting && (
        <CreditNoteModal
          invoice={invoice}
          onClose={() => setCrediting(false)}
          onDone={() => {
            setCrediting(false);
            setChanges((n) => n + 1);
          }}
        />
      )}
    </section>
  );
}
