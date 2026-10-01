import { useCallback, useState } from "react";
import { Link } from "react-router-dom";
import { fetchRefunds, voidRefund, type Refund } from "../api/sales";
import { Pager, SearchBox } from "../crm/ui";
import { useAppData } from "../data/AppDataProvider";
import { dayDate, docStatusClass, inr } from "../lib/format";
import { PAGE_SIZE, usePaged } from "../lib/usePaged";
import { ReasonModal } from "../sales/ReasonModal";

/** Money paid back to customers. Refunds start from a payment's advance or an invoice's credit balance. */
export function Refunds() {
  const { can, version } = useAppData();
  const [search, setSearch] = useState("");
  const onSearch = useCallback((q: string) => setSearch(q), []);
  const [voiding, setVoiding] = useState<Refund | null>(null);
  const list = usePaged((limit, offset) => fetchRefunds({ q: search, limit, offset }), search, version);

  return (
    <section>
      <div className="page-head">
        <div className="eyebrow">Sales</div>
        <h1 className="page-title">Refunds</h1>
        <p className="page-sub">
          Money paid back to customers. To refund, open a payment with an advance left, or an invoice the customer is owed money on
          after a credit note.
        </p>
      </div>
      <div className="toolbar">
        <div />
        <SearchBox value={search} onChange={onSearch} placeholder="Refund no., customer or reference" />
      </div>
      {list.error && <div className="error-banner">{list.error}</div>}
      {!list.loading && list.total === 0 && (
        <div className="card" style={{ textAlign: "center", color: "var(--ink-dim)" }}>
          {search ? "No refunds match." : "No refunds yet."}
        </div>
      )}
      {list.rows.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Refund</th>
                <th>Date</th>
                <th>Customer</th>
                <th>Mode</th>
                <th className="num">Amount</th>
                <th>From</th>
                <th>Reason</th>
                <th>Status</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {list.rows.map((f) => (
                <tr key={f.id}>
                  <td className="mono">{f.number}</td>
                  <td>{dayDate(f.refund_date)}</td>
                  <td>{f.customer_name}</td>
                  <td>
                    {f.mode}
                    {f.reference && <small className="mono"> {f.reference}</small>}
                  </td>
                  <td className="num">{inr(f.amount)}</td>
                  <td className="mono">
                    {f.invoice_id ? <Link to={`/sales/invoices/${f.invoice_id}`}>{f.source_number}</Link> : f.source_number}
                  </td>
                  <td>
                    {f.reason}
                    {f.status === "Voided" && <small className="below-list">Voided — {f.void_reason}</small>}
                  </td>
                  <td>
                    <span className={`badge ${docStatusClass(f.status)}`}>{f.status}</span>
                  </td>
                  <td>
                    {can("sales.payment.write") && f.status === "Paid" && (
                      <button className="secondary-btn" onClick={() => setVoiding(f)}>
                        Void
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <Pager page={list.page} pageSize={PAGE_SIZE} total={list.total} onPage={list.setPage} />
      {voiding && (
        <ReasonModal
          title={`Void ${voiding.number}?`}
          label="Why? (e.g. entered twice) — the amount will be owed back to the customer again."
          action="Void refund"
          onClose={() => setVoiding(null)}
          onConfirm={async (reason) => {
            await voidRefund(voiding.id, reason);
            setVoiding(null);
            void list.reload();
          }}
        />
      )}
    </section>
  );
}
