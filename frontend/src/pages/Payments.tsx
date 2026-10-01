import { useCallback, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError } from "../api/client";
import { allocatePayment, fetchPayment, fetchPayments, setTdsCertificate, voidPayment, type Receipt } from "../api/sales";
import { ExportButton } from "../components/ExportButton";
import { SavedViews } from "../components/SavedViews";
import { recallFilters } from "../lib/filterMemory";
import { Drawer, ErrorNote, Pager, SearchBox } from "../crm/ui";
import { useAppData } from "../data/AppDataProvider";
import { dayDate, docStatusClass, inr } from "../lib/format";
import { PAGE_SIZE, usePaged } from "../lib/usePaged";
import { PaymentModal } from "../sales/PaymentModal";
import { ReasonModal } from "../sales/ReasonModal";
import { RefundModal } from "../sales/RefundModal";
import { SendModal } from "../sales/SendModal";

export function Payments() {
  const { can, version } = useAppData();
  const [search, setSearch] = useState(() => String(recallFilters("payments").search ?? ""));
  const onSearch = useCallback((q: string) => setSearch(q), []);
  const [advancesOnly, setAdvancesOnly] = useState(() => recallFilters("payments").advance === "yes");
  const [error, setError] = useState<string | null>(null);
  const [recording, setRecording] = useState(false);
  const [opened, setOpened] = useState<Receipt | null>(null);
  const list = usePaged(
    (limit, offset) => fetchPayments({ q: search, with_advance: advancesOnly || undefined, limit, offset }),
    `${search}|${advancesOnly}`,
    version,
  );

  return (
    <section>
      <div className="page-head">
        <div className="eyebrow">Sales</div>
        <h1 className="page-title">Payments received</h1>
        <p className="page-sub">Money in from customers, and which invoices it paid. Anything not applied is kept as an advance.</p>
      </div>
      <div className="toolbar">
        <div className="filters">
          <button className={!advancesOnly ? "on" : ""} onClick={() => setAdvancesOnly(false)}>
            All
          </button>
          <button className={advancesOnly ? "on" : ""} onClick={() => setAdvancesOnly(true)}>
            With advance left
          </button>
        </div>
        <SavedViews
          page="payments"
          filters={{ advance: advancesOnly ? "yes" : "", search }}
          onApply={(f) => (setAdvancesOnly(f.advance === "yes"), setSearch(String(f.search ?? "")))}
        />
        <SearchBox value={search} onChange={onSearch} placeholder="Receipt no., customer or reference" />
        <ExportButton kind="payments" filters={{ q: search, with_advance: advancesOnly || undefined }} onError={setError} />
        {can("sales.payment.write") && (
          <button className="primary-btn" onClick={() => setRecording(true)}>
            + Record payment
          </button>
        )}
      </div>
      {(error ?? list.error) && <div className="error-banner">{error ?? list.error}</div>}
      {!list.loading && list.total === 0 && (
        <div className="card" style={{ textAlign: "center", color: "var(--ink-dim)" }}>
          {search || advancesOnly ? "No payments match." : "No payments recorded yet."}
        </div>
      )}
      {list.rows.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Receipt</th>
                <th>Date</th>
                <th>Customer</th>
                <th>Mode</th>
                <th className="num">Amount</th>
                <th>Applied to</th>
                <th className="num">Advance</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {list.rows.map((r) => (
                <tr key={r.id} className="clickable" onClick={() => setOpened(r)}>
                  <td className="mono">{r.number}</td>
                  <td>{dayDate(r.receipt_date)}</td>
                  <td>{r.customer_name}</td>
                  <td>
                    {r.mode}
                    {r.reference && <small className="mono"> {r.reference}</small>}
                  </td>
                  <td className="num">{inr(r.amount)}</td>
                  <td className="mono">{r.allocations.map((a) => a.invoice_number).join(", ") || "—"}</td>
                  <td className="num">{r.unallocated > 0 ? inr(r.unallocated) : "—"}</td>
                  <td>
                    <span className={`badge ${docStatusClass(r.status === "Received" ? "Paid" : "Voided")}`}>{r.status}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <Pager page={list.page} pageSize={PAGE_SIZE} total={list.total} onPage={list.setPage} />
      {recording && (
        <PaymentModal
          onClose={() => setRecording(false)}
          onDone={(r) => {
            setRecording(false);
            setOpened(r);
            void list.reload();
          }}
        />
      )}
      {opened && (
        <ReceiptDrawer
          receipt={opened}
          onClose={() => setOpened(null)}
          onChanged={(r) => {
            setOpened(r);
            void list.reload();
          }}
        />
      )}
    </section>
  );
}

function ReceiptDrawer({ receipt: r, onClose, onChanged }: { receipt: Receipt; onClose: () => void; onChanged: (r: Receipt) => void }) {
  const { can } = useAppData();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [voiding, setVoiding] = useState(false);
  const [sending, setSending] = useState(false);
  const [refunding, setRefunding] = useState(false);
  const canWrite = can("sales.payment.write") && r.status === "Received";

  async function applyAdvance() {
    setBusy(true);
    setError(null);
    try {
      onChanged(await allocatePayment(r.id));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't apply the advance.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Drawer title={r.number} subtitle={`${r.customer_name} · ${dayDate(r.receipt_date)}`} onClose={onClose}>
      <ErrorNote message={error} />
      {r.status === "Voided" && <div className="error-banner">Voided — {r.void_reason}</div>}
      <dl className="doc-totals" style={{ marginLeft: 0, maxWidth: "none" }}>
        <div>
          <dt>Amount</dt>
          <dd className="num">{inr(r.amount)}</dd>
        </div>
        <div>
          <dt>Mode</dt>
          <dd>
            {r.mode} {r.reference && <span className="mono">{r.reference}</span>}
          </dd>
        </div>
        <div>
          <dt>Applied to invoices</dt>
          <dd className="num">{inr(r.allocated)}</dd>
        </div>
        {r.tds_amount > 0 && (
          <div>
            <dt>TDS deducted ({r.tds_section})</dt>
            <dd className="num">{inr(r.tds_amount)}</dd>
          </div>
        )}
        {r.refunded > 0 && (
          <div>
            <dt>Refunded</dt>
            <dd className="num">{inr(r.refunded)}</dd>
          </div>
        )}
        <div className="grand">
          <dt>Advance left</dt>
          <dd className="num">{inr(r.unallocated)}</dd>
        </div>
      </dl>
      {r.tds_amount > 0 && (
        <label className="field checkbox-field" style={{ marginTop: 12 }}>
          <input
            type="checkbox"
            checked={r.tds_certificate_received}
            disabled={!can("sales.payment.write") || busy}
            onChange={async (e) => {
              setBusy(true);
              try {
                onChanged(await setTdsCertificate(r.id, e.target.checked));
              } catch (err) {
                setError(err instanceof ApiError ? err.message : "Couldn't save.");
              } finally {
                setBusy(false);
              }
            }}
          />
          <span>TDS certificate (Form 16A) received</span>
        </label>
      )}
      {r.allocations.length > 0 && (
        <div className="mini-docs" style={{ marginTop: 16 }}>
          {r.allocations.map((a) => (
            <div className="row" key={a.invoice_id}>
              <Link className="mono" to={`/sales/invoices/${a.invoice_id}`}>
                {a.invoice_number}
              </Link>
              <span className="num">
                {inr(a.amount)}
                {a.tds_amount > 0 && <small> + {inr(a.tds_amount)} TDS</small>}
              </span>
            </div>
          ))}
        </div>
      )}
      {r.notes && <p className="card-note">{r.notes}</p>}
      <div className="head-actions" style={{ marginTop: 16 }}>
        <a className="ghost-btn" href={`/print/receipt/${r.id}`} target="_blank" rel="noreferrer">
          Print receipt
        </a>
        {r.status === "Received" && (
          <button className="ghost-btn" onClick={() => setSending(true)}>
            Send receipt
          </button>
        )}
        {canWrite && r.unallocated > 0 && (
          <button className="primary-btn" disabled={busy} onClick={applyAdvance}>
            Apply advance to unpaid invoices
          </button>
        )}
        {canWrite && r.unallocated > 0 && (
          <button className="ghost-btn" disabled={busy} onClick={() => setRefunding(true)}>
            Refund advance
          </button>
        )}
        {canWrite && (
          <button className="danger-btn" disabled={busy} onClick={() => setVoiding(true)}>
            Void
          </button>
        )}
      </div>
      {sending && <SendModal kind="receipt" id={r.id} customerId={r.customer_id} title={`receipt ${r.number}`} onClose={() => setSending(false)} />}
      {refunding && (
        <RefundModal
          source={{ receipt_id: r.id, number: r.number, customer_name: r.customer_name, available: r.unallocated }}
          onClose={() => setRefunding(false)}
          onDone={async () => {
            setRefunding(false);
            onChanged(await fetchPayment(r.id));
          }}
        />
      )}
      {voiding && (
        <ReasonModal
          title={`Void ${r.number}?`}
          label="Why? (e.g. cheque bounced) — its invoices will be owed again."
          action="Void payment"
          onClose={() => setVoiding(false)}
          onConfirm={async (reason) => {
            onChanged(await voidPayment(r.id, reason));
            setVoiding(false);
          }}
        />
      )}
    </Drawer>
  );
}
