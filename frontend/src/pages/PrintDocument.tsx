import { useEffect, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { ApiError, type Quotation } from "../api/client";
import {
  fetchCompanyProfile,
  fetchCreditNote,
  fetchDelivery,
  fetchInvoice,
  fetchOrder,
  fetchPayment,
  fetchQuotation,
  fetchStatement,
  type CompanyProfile,
  type CreditNote,
  type DeliveryNote,
  type Invoice,
  type Receipt,
  type Statement,
  type SalesOrder,
} from "../api/sales";
import { dayDate } from "../lib/format";
import { StatementTable } from "./StatementPage";

const money = (n: number) => n.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

/** Print-ready documents at /print/invoice/:id and /print/delivery/:id — no app chrome; use the browser's Print / Save as PDF. */
export function PrintDocument({ kind }: { kind: "invoice" | "delivery" | "credit-note" | "receipt" | "statement" | "quotation" }) {
  const { id = "" } = useParams();
  const [search] = useSearchParams();
  const [quote, setQuote] = useState<{ q: Quotation; company: CompanyProfile } | null>(null);
  const [statement, setStatement] = useState<{ data: Statement; company: CompanyProfile } | null>(null);
  const [invoice, setInvoice] = useState<Invoice | null>(null);
  const [delivery, setDelivery] = useState<{ note: DeliveryNote; order: SalesOrder; company: CompanyProfile } | null>(null);
  const [credit, setCredit] = useState<CreditNote | null>(null);
  const [receipt, setReceipt] = useState<{ receipt: Receipt; company: CompanyProfile } | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const load =
      kind === "invoice"
        ? fetchInvoice(id).then(setInvoice)
        : kind === "credit-note"
          ? fetchCreditNote(id).then(setCredit)
          : kind === "receipt"
            ? Promise.all([fetchPayment(id), fetchCompanyProfile()]).then(([r, company]) => setReceipt({ receipt: r, company }))
            : kind === "quotation"
              ? Promise.all([fetchQuotation(id), fetchCompanyProfile()]).then(([q, company]) => setQuote({ q, company }))
            : kind === "statement"
              ? Promise.all([fetchStatement(id, search.get("from") ?? undefined, search.get("to") ?? undefined), fetchCompanyProfile()]).then(
                  ([data, company]) => setStatement({ data, company }),
                )
          : fetchDelivery(id).then(async (note) => {
            const [order, company] = await Promise.all([fetchOrder(note.order_id), fetchCompanyProfile()]);
            setDelivery({ note, order, company });
          });
    load.catch((err) => setError(err instanceof ApiError ? err.message : "Couldn't load the document."));
  }, [id, kind, search]);

  useEffect(() => {
    const title =
      invoice?.number ?? delivery?.note.number ?? credit?.number ?? receipt?.receipt.number ?? quote?.q.number ?? (statement && `Statement ${statement.data.customer_name}`);
    if (title) document.title = title.replace(/\//g, "-");
  }, [invoice, delivery, credit, receipt, statement, quote]);

  if (error) return <p className="print-error">{error}</p>;
  if (!invoice && !delivery && !credit && !receipt && !statement && !quote) return <p className="print-error">Loading…</p>;

  return (
    <div className="print-shell">
      <div className="print-bar">
        <button className="primary-btn" onClick={() => window.print()}>
          Print / Save as PDF
        </button>
        <button className="ghost-btn" onClick={() => window.close()}>
          Close
        </button>
      </div>
      {invoice ? (
        <InvoiceSheet inv={invoice} />
      ) : credit ? (
        <CreditSheet note={credit} />
      ) : receipt ? (
        <ReceiptSheet {...receipt} />
      ) : quote ? (
        <QuotationSheet {...quote} />
      ) : statement ? (
        <StatementSheet {...statement} />
      ) : (
        <ChallanSheet {...delivery!} />
      )}
    </div>
  );
}

export function InvoiceSheet({ inv }: { inv: Invoice }) {
  const interstate = inv.igst > 0 || (inv.cgst === 0 && inv.sgst === 0 && inv.place_of_supply !== inv.seller_state);
  return (
    <article className="print-doc">
      <header className="pd-head">
        <div>
          <h1>{inv.seller_name}</h1>
          <p className="pre">{inv.seller_address}</p>
          <p>
            GSTIN <b className="mono">{inv.seller_gstin}</b> · State {inv.seller_state} {inv.seller_state_name}
          </p>
        </div>
        <div className="pd-title">
          <h2>{inv.status === "Draft" ? "DRAFT — NOT A TAX INVOICE" : "TAX INVOICE"}</h2>
          <small>Original for recipient</small>
          {inv.irn && (
            <small className="mono" style={{ display: "block", wordBreak: "break-all", maxWidth: 260 }}>
              IRN {inv.irn}
              {inv.irn_ack_no && ` · Ack ${inv.irn_ack_no}`}
              {inv.irn_ack_date && ` · ${dayDate(inv.irn_ack_date)}`}
            </small>
          )}
        </div>
      </header>

      <section className="pd-meta">
        <div>
          <h3>Bill to</h3>
          <p>
            <b>{inv.buyer_name}</b>
          </p>
          <p className="pre">{inv.billing_address}</p>
          <p>{inv.buyer_gstin ? <>GSTIN <b className="mono">{inv.buyer_gstin}</b></> : "Unregistered"}</p>
          {inv.buyer_state && <p>State code {inv.buyer_state}</p>}
        </div>
        {inv.shipping_address && inv.shipping_address !== inv.billing_address && (
          <div>
            <h3>Ship to</h3>
            <p className="pre">{inv.shipping_address}</p>
          </div>
        )}
        <dl>
          <dt>Invoice no.</dt>
          <dd className="mono">{inv.number ?? "—"}</dd>
          <dt>Invoice date</dt>
          <dd>{dayDate(inv.invoice_date)}</dd>
          <dt>Due date</dt>
          <dd>{dayDate(inv.due_date)}</dd>
          <dt>Place of supply</dt>
          <dd>
            {inv.place_of_supply} {inv.place_of_supply_name}
          </dd>
          <dt>Reverse charge</dt>
          <dd>No</dd>
          <dt>Order</dt>
          <dd className="mono">{inv.order_number}</dd>
          {inv.eway_bill_no && (
            <>
              <dt>e-Way bill</dt>
              <dd className="mono">
                {inv.eway_bill_no}
                {inv.eway_bill_date && ` · ${dayDate(inv.eway_bill_date)}`}
              </dd>
            </>
          )}
          {inv.customer_po && (
            <>
              <dt>Customer PO</dt>
              <dd>{inv.customer_po}</dd>
            </>
          )}
        </dl>
      </section>

      <table className="pd-lines">
        <thead>
          <tr>
            <th>#</th>
            <th>Description</th>
            <th>HSN/SAC</th>
            <th className="num">Qty</th>
            <th className="num">Rate</th>
            <th className="num">Taxable value</th>
            {interstate ? (
              <th className="num">IGST</th>
            ) : (
              <>
                <th className="num">CGST</th>
                <th className="num">SGST</th>
              </>
            )}
            <th className="num">Total</th>
          </tr>
        </thead>
        <tbody>
          {inv.lines.map((l, i) => (
            <tr key={l.id}>
              <td>{i + 1}</td>
              <td>{l.description}</td>
              <td className="mono">{l.hsn_code}</td>
              <td className="num">
                {l.qty} {l.uom}
              </td>
              <td className="num">
                {money(l.unit_price)}
                {l.discount_pct ? <div className="print-sub">less {l.discount_pct}%</div> : null}
              </td>
              <td className="num">{money(l.taxable_value)}</td>
              {interstate ? (
                <td className="num">
                  {money(l.igst)}
                  <small>{l.gst_rate}%</small>
                </td>
              ) : (
                <>
                  <td className="num">
                    {money(l.cgst)}
                    <small>{l.gst_rate / 2}%</small>
                  </td>
                  <td className="num">
                    {money(l.sgst)}
                    <small>{l.gst_rate / 2}%</small>
                  </td>
                </>
              )}
              <td className="num">{money(l.taxable_value + l.cgst + l.sgst + l.igst)}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <section className="pd-sum">
        <div>
          <p>
            <b>Amount in words:</b> {inv.amount_in_words}
          </p>
          <table className="pd-hsn">
            <thead>
              <tr>
                <th>HSN/SAC</th>
                <th className="num">Taxable</th>
                <th className="num">Rate</th>
                <th className="num">{interstate ? "IGST" : "CGST + SGST"}</th>
              </tr>
            </thead>
            <tbody>
              {inv.hsn_summary.map((h) => (
                <tr key={`${h.hsn_code}-${h.gst_rate}`}>
                  <td className="mono">{h.hsn_code}</td>
                  <td className="num">{money(h.taxable_value)}</td>
                  <td className="num">{h.gst_rate}%</td>
                  <td className="num">{money(h.cgst + h.sgst + h.igst)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <dl>
          {inv.discount_pct > 0 && (
            <>
              <dt>Gross</dt>
              <dd>{money(inv.subtotal)}</dd>
              <dt>Discount {inv.discount_pct}%</dt>
              <dd>−{money(inv.subtotal - inv.total)}</dd>
            </>
          )}
          <dt>Taxable value</dt>
          <dd>{money(inv.total)}</dd>
          {interstate ? (
            <>
              <dt>IGST</dt>
              <dd>{money(inv.igst)}</dd>
            </>
          ) : (
            <>
              <dt>CGST</dt>
              <dd>{money(inv.cgst)}</dd>
              <dt>SGST</dt>
              <dd>{money(inv.sgst)}</dd>
            </>
          )}
          {inv.round_off !== 0 && (
            <>
              <dt>Round off</dt>
              <dd>{money(inv.round_off)}</dd>
            </>
          )}
          <dt className="grand">Total</dt>
          <dd className="grand">₹{money(inv.grand_total)}</dd>
        </dl>
      </section>

      <footer className="pd-foot">
        <div>
          {inv.bank_details && (
            <>
              <h3>Bank details</h3>
              <p className="pre">{inv.bank_details}</p>
            </>
          )}
          {inv.terms && (
            <>
              <h3>Terms</h3>
              <p className="pre">{inv.terms}</p>
            </>
          )}
        </div>
        <div className="pd-sign">
          <p>For {inv.seller_name}</p>
          <p className="sig">Authorised signatory</p>
        </div>
      </footer>
    </article>
  );
}

export function ChallanSheet({ note, order, company }: { note: DeliveryNote; order: SalesOrder; company: CompanyProfile }) {
  return (
    <article className="print-doc">
      <header className="pd-head">
        <div>
          <h1>{company.legal_name || company.name}</h1>
          <p className="pre">{company.address}</p>
          {company.gstin && (
            <p>
              GSTIN <b className="mono">{company.gstin}</b>
            </p>
          )}
        </div>
        <div className="pd-title">
          <h2>DELIVERY CHALLAN</h2>
          {note.status === "Cancelled" && <small>CANCELLED — {note.cancel_reason}</small>}
        </div>
      </header>
      <section className="pd-meta">
        <div>
          <h3>Deliver to</h3>
          <p>
            <b>{note.customer_name}</b>
          </p>
          <p className="pre">{note.shipping_address}</p>
          {order.customer_gstin && (
            <p>
              GSTIN <b className="mono">{order.customer_gstin}</b>
            </p>
          )}
        </div>
        <dl>
          <dt>Challan no.</dt>
          <dd className="mono">{note.number}</dd>
          <dt>Date</dt>
          <dd>{dayDate(note.delivery_date)}</dd>
          <dt>Order</dt>
          <dd className="mono">{note.order_number}</dd>
          {order.customer_po && (
            <>
              <dt>Customer PO</dt>
              <dd>{order.customer_po}</dd>
            </>
          )}
          {note.vehicle_no && (
            <>
              <dt>Vehicle</dt>
              <dd className="mono">{note.vehicle_no}</dd>
            </>
          )}
          {note.transporter && (
            <>
              <dt>Transporter</dt>
              <dd>{note.transporter}</dd>
            </>
          )}
        </dl>
      </section>
      <table className="pd-lines">
        <thead>
          <tr>
            <th>#</th>
            <th>Description</th>
            <th className="num">Quantity</th>
          </tr>
        </thead>
        <tbody>
          {note.lines.map((l, i) => (
            <tr key={l.order_line_id}>
              <td>{i + 1}</td>
              <td>{l.description}</td>
              <td className="num">
                {l.qty} {l.uom}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {note.notes && <p className="pre">{note.notes}</p>}
      <footer className="pd-foot">
        <div className="pd-sign">
          <p>Received in good condition</p>
          <p className="sig">Receiver's signature</p>
        </div>
        <div className="pd-sign">
          <p>For {company.legal_name || company.name}</p>
          <p className="sig">Authorised signatory</p>
        </div>
      </footer>
    </article>
  );
}

export function CreditSheet({ note }: { note: CreditNote }) {
  const interstate = note.igst > 0;
  return (
    <article className="print-doc">
      <header className="pd-head">
        <div>
          <h1>{note.seller_name}</h1>
          <p className="pre">{note.seller_address}</p>
          <p>
            GSTIN <b className="mono">{note.seller_gstin}</b>
          </p>
        </div>
        <div className="pd-title">
          <h2>CREDIT NOTE</h2>
          <small>{note.kind}</small>
        </div>
      </header>
      <section className="pd-meta">
        <div>
          <h3>Issued to</h3>
          <p>
            <b>{note.customer_name}</b>
          </p>
          <p className="pre">{note.billing_address}</p>
          <p>{note.buyer_gstin ? <>GSTIN <b className="mono">{note.buyer_gstin}</b></> : "Unregistered"}</p>
        </div>
        <dl>
          <dt>Credit note no.</dt>
          <dd className="mono">{note.number}</dd>
          <dt>Date</dt>
          <dd>{dayDate(note.note_date)}</dd>
          <dt>Against invoice</dt>
          <dd className="mono">{note.invoice_number}</dd>
          <dt>Invoice date</dt>
          <dd>{dayDate(note.invoice_date)}</dd>
          <dt>Place of supply</dt>
          <dd>
            {note.place_of_supply} {note.place_of_supply_name}
          </dd>
        </dl>
      </section>
      <p>
        <b>Reason:</b> {note.reason}
      </p>
      <table className="pd-lines">
        <thead>
          <tr>
            <th>#</th>
            <th>Description</th>
            <th>HSN/SAC</th>
            <th className="num">Qty</th>
            <th className="num">Taxable value</th>
            {interstate ? (
              <th className="num">IGST</th>
            ) : (
              <>
                <th className="num">CGST</th>
                <th className="num">SGST</th>
              </>
            )}
            <th className="num">Total</th>
          </tr>
        </thead>
        <tbody>
          {note.lines.map((l, i) => (
            <tr key={l.invoice_line_id}>
              <td>{i + 1}</td>
              <td>{l.description}</td>
              <td className="mono">{l.hsn_code}</td>
              <td className="num">{l.qty ? `${l.qty} ${l.uom}` : "—"}</td>
              <td className="num">{money(l.taxable_value)}</td>
              {interstate ? (
                <td className="num">
                  {money(l.igst)}
                  <small>{l.gst_rate}%</small>
                </td>
              ) : (
                <>
                  <td className="num">
                    {money(l.cgst)}
                    <small>{l.gst_rate / 2}%</small>
                  </td>
                  <td className="num">
                    {money(l.sgst)}
                    <small>{l.gst_rate / 2}%</small>
                  </td>
                </>
              )}
              <td className="num">{money(l.taxable_value + l.cgst + l.sgst + l.igst)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <section className="pd-sum">
        <p>
          <b>Amount in words:</b> {note.amount_in_words}
        </p>
        <dl>
          <dt>Taxable value</dt>
          <dd>{money(note.total)}</dd>
          {interstate ? (
            <>
              <dt>IGST</dt>
              <dd>{money(note.igst)}</dd>
            </>
          ) : (
            <>
              <dt>CGST</dt>
              <dd>{money(note.cgst)}</dd>
              <dt>SGST</dt>
              <dd>{money(note.sgst)}</dd>
            </>
          )}
          {note.round_off !== 0 && (
            <>
              <dt>Round off</dt>
              <dd>{money(note.round_off)}</dd>
            </>
          )}
          <dt className="grand">Credit</dt>
          <dd className="grand">₹{money(note.grand_total)}</dd>
        </dl>
      </section>
      <footer className="pd-foot">
        <div />
        <div className="pd-sign">
          <p>For {note.seller_name}</p>
          <p className="sig">Authorised signatory</p>
        </div>
      </footer>
    </article>
  );
}

export function ReceiptSheet({ receipt: r, company }: { receipt: Receipt; company: CompanyProfile }) {
  return (
    <article className="print-doc">
      <header className="pd-head">
        <div>
          <h1>{company.legal_name || company.name}</h1>
          <p className="pre">{company.address}</p>
          {company.gstin && (
            <p>
              GSTIN <b className="mono">{company.gstin}</b>
            </p>
          )}
        </div>
        <div className="pd-title">
          <h2>PAYMENT RECEIPT</h2>
          {r.status === "Voided" && <small>VOIDED — {r.void_reason}</small>}
        </div>
      </header>
      <section className="pd-meta">
        <div>
          <h3>Received from</h3>
          <p>
            <b>{r.customer_name}</b>
          </p>
          <p style={{ marginTop: 12 }}>
            The sum of <b>₹{money(r.amount)}</b> ({r.amount_in_words}) by {r.mode.toLowerCase()}
            {r.reference && <> — ref. <span className="mono">{r.reference}</span></>}.
          </p>
        </div>
        <dl>
          <dt>Receipt no.</dt>
          <dd className="mono">{r.number}</dd>
          <dt>Date</dt>
          <dd>{dayDate(r.receipt_date)}</dd>
        </dl>
      </section>
      {(r.allocations.length > 0 || r.unallocated > 0) && (
        <table className="pd-lines">
          <thead>
            <tr>
              <th>Against invoice</th>
              <th className="num">Amount</th>
            </tr>
          </thead>
          <tbody>
            {r.allocations.map((a) => (
              <tr key={a.invoice_id}>
                <td className="mono">{a.invoice_number}</td>
                <td className="num">{money(a.amount)}</td>
              </tr>
            ))}
            {r.unallocated > 0 && (
              <tr>
                <td>Advance (to be adjusted against future invoices)</td>
                <td className="num">{money(r.unallocated)}</td>
              </tr>
            )}
          </tbody>
        </table>
      )}
      <footer className="pd-foot">
        <p>{r.mode === "Cheque" ? "Subject to realisation of the cheque." : ""}</p>
        <div className="pd-sign">
          <p>For {company.legal_name || company.name}</p>
          <p className="sig">Authorised signatory</p>
        </div>
      </footer>
    </article>
  );
}

export function StatementSheet({ data, company }: { data: Statement; company: CompanyProfile }) {
  return (
    <article className="print-doc">
      <header className="pd-head">
        <div>
          <h1>{company.legal_name || company.name}</h1>
          <p className="pre">{company.address}</p>
          {company.gstin && (
            <p>
              GSTIN <b className="mono">{company.gstin}</b>
            </p>
          )}
        </div>
        <div className="pd-title">
          <h2>STATEMENT OF ACCOUNT</h2>
          <small>
            {dayDate(data.date_from)} – {dayDate(data.date_to)}
          </small>
        </div>
      </header>
      <section className="pd-meta">
        <div>
          <h3>Customer</h3>
          <p>
            <b>{data.customer_name}</b>
          </p>
          <p className="pre">{data.billing_address}</p>
          {data.gstin && (
            <p>
              GSTIN <b className="mono">{data.gstin}</b>
            </p>
          )}
        </div>
        <dl>
          <dt>Balance due</dt>
          <dd>
            <b>₹{money(data.closing_balance)}</b>
          </dd>
        </dl>
      </section>
      <div className="pd-statement">
        <StatementTable data={data} links={false} />
      </div>
      {company.bank_details && (
        <footer className="pd-foot">
          <div>
            <h3>Pay to</h3>
            <p className="pre">{company.bank_details}</p>
          </div>
        </footer>
      )}
    </article>
  );
}

export function QuotationSheet({ q, company }: { q: Quotation; company: CompanyProfile }) {
  const interstate = q.igst > 0;
  return (
    <article className="print-doc">
      <header className="pd-head">
        <div>
          <h1>{company.legal_name || company.name}</h1>
          <p className="pre">{company.address}</p>
          {company.gstin && (
            <p>
              GSTIN <b className="mono">{company.gstin}</b>
            </p>
          )}
          {(company.phone || company.email) && <p>{[company.phone, company.email].filter(Boolean).join(" · ")}</p>}
        </div>
        <div className="pd-title">
          <h2>QUOTATION</h2>
          {q.status === "Pending approval" && <small>DRAFT — awaiting approval</small>}
        </div>
      </header>
      <section className="pd-meta">
        <div>
          <h3>For</h3>
          <p>
            <b>{q.customer_name}</b>
          </p>
          <p className="pre">{q.billing_address}</p>
          {q.customer_gstin && (
            <p>
              GSTIN <b className="mono">{q.customer_gstin}</b>
            </p>
          )}
        </div>
        <dl>
          <dt>Quotation no.</dt>
          <dd className="mono">{q.number}</dd>
          <dt>Date</dt>
          <dd>{dayDate(q.created_at)}</dd>
          {q.valid_until && (
            <>
              <dt>Valid until</dt>
              <dd>{dayDate(q.valid_until)}</dd>
            </>
          )}
          {q.created_by_name && (
            <>
              <dt>Prepared by</dt>
              <dd>{q.created_by_name}</dd>
            </>
          )}
        </dl>
      </section>
      <table className="pd-lines">
        <thead>
          <tr>
            <th>#</th>
            <th>Description</th>
            <th>HSN/SAC</th>
            <th className="num">Qty</th>
            <th className="num">Rate</th>
            <th className="num">Amount</th>
            <th className="num">GST</th>
          </tr>
        </thead>
        <tbody>
          {q.lines.map((l, i) => (
            <tr key={i}>
              <td>{i + 1}</td>
              <td>{l.item_name}</td>
              <td className="mono">{l.hsn_code}</td>
              <td className="num">
                {l.qty} {l.uom}
              </td>
              <td className="num">
                {money(l.unit_price)}
                {l.discount_pct ? <div className="print-sub">less {l.discount_pct}%</div> : null}
              </td>
              <td className="num">{money(l.line_total * (1 - (l.discount_pct ?? 0) / 100))}</td>
              <td className="num">{l.gst_rate ?? 0}%</td>
            </tr>
          ))}
        </tbody>
      </table>
      <section className="pd-sum">
        <div>{q.notes && <p className="pre">{q.notes}</p>}</div>
        <dl>
          {q.discount_pct > 0 && (
            <>
              <dt>Gross</dt>
              <dd>{money(q.subtotal)}</dd>
              <dt>Discount {q.discount_pct}%</dt>
              <dd>−{money(q.subtotal - q.total)}</dd>
            </>
          )}
          <dt>Taxable value</dt>
          <dd>{money(q.total)}</dd>
          {interstate ? (
            <>
              <dt>IGST</dt>
              <dd>{money(q.igst)}</dd>
            </>
          ) : (
            <>
              <dt>CGST</dt>
              <dd>{money(q.cgst)}</dd>
              <dt>SGST</dt>
              <dd>{money(q.sgst)}</dd>
            </>
          )}
          {q.round_off !== 0 && (
            <>
              <dt>Round off</dt>
              <dd>{money(q.round_off)}</dd>
            </>
          )}
          <dt className="grand">Total</dt>
          <dd className="grand">₹{money(q.grand_total)}</dd>
        </dl>
      </section>
      <footer className="pd-foot">
        <div>{company.invoice_terms && <p className="pre">{company.invoice_terms}</p>}</div>
        <div className="pd-sign">
          <p>For {company.legal_name || company.name}</p>
          <p className="sig">Authorised signatory</p>
        </div>
      </footer>
    </article>
  );
}
