import { useCallback, useState } from "react";
import { Link } from "react-router-dom";
import { fetchInvoices } from "../api/sales";
import { ExportButton } from "../components/ExportButton";
import { SavedViews } from "../components/SavedViews";
import { recallFilters } from "../lib/filterMemory";
import { Pager, SearchBox } from "../crm/ui";
import { useAppData } from "../data/AppDataProvider";
import { dayDate, docStatusClass, inr } from "../lib/format";
import { PAGE_SIZE, usePaged } from "../lib/usePaged";

const FILTERS = [
  { key: "", label: "All" },
  { key: "Draft", label: "Drafts" },
  { key: "unpaid", label: "Unpaid" },
  { key: "overdue", label: "Overdue" },
  { key: "paid", label: "Paid" },
];

export function Invoices() {
  const { version } = useAppData();
  const [status, setStatus] = useState(() => String(recallFilters("invoices").status ?? ""));
  const [search, setSearch] = useState(() => String(recallFilters("invoices").search ?? ""));
  const [error, setError] = useState<string | null>(null);
  const onSearch = useCallback((q: string) => setSearch(q), []);
  const list = usePaged((limit, offset) => fetchInvoices({ status, q: search, limit, offset }), `${status}|${search}`, version);

  return (
    <section>
      <div className="page-head">
        <div className="eyebrow">Sales</div>
        <h1 className="page-title">Invoices</h1>
        <p className="page-sub">GST tax invoices. Raise one from a confirmed order; once issued it's numbered and locked.</p>
      </div>
      <div className="toolbar">
        <div className="filters">
          {FILTERS.map((f) => (
            <button key={f.key} className={status === f.key ? "on" : ""} onClick={() => setStatus(f.key)}>
              {f.label}
            </button>
          ))}
        </div>
        <SavedViews
          page="invoices"
          filters={{ status, search }}
          onApply={(f) => (setStatus(String(f.status ?? "")), setSearch(String(f.search ?? "")))}
        />
        <SearchBox value={search} onChange={onSearch} placeholder="Invoice no., customer or PO" />
        <ExportButton kind="invoices" filters={{ status, q: search }} onError={setError} />
      </div>
      {(error ?? list.error) && <div className="error-banner">{error ?? list.error}</div>}
      {!list.loading && list.total === 0 && (
        <div className="card" style={{ textAlign: "center", color: "var(--ink-dim)" }}>
          {status || search ? "No invoices match this filter." : "No invoices yet. Open a confirmed order and choose Create invoice."}
        </div>
      )}
      {list.rows.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Invoice</th>
                <th>Date</th>
                <th>Customer</th>
                <th>Due</th>
                <th className="num">Total</th>
                <th className="num">Balance</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {list.rows.map((i) => (
                <tr key={i.id}>
                  <td>
                    <Link className="link-btn mono" style={{ padding: 0 }} to={`/sales/invoices/${i.id}`}>
                      {i.number ?? "Draft"}
                    </Link>
                  </td>
                  <td>{i.status === "Draft" ? "—" : dayDate(i.invoice_date)}</td>
                  <td>{i.customer_name}</td>
                  <td>{i.status === "Draft" ? "—" : dayDate(i.due_date)}</td>
                  <td className="num">{inr(i.grand_total)}</td>
                  <td className="num">{i.status === "Draft" ? "—" : inr(i.balance)}</td>
                  <td>
                    <span className={`badge ${docStatusClass(i.payment_status)}`}>{i.payment_status}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <Pager page={list.page} pageSize={PAGE_SIZE} total={list.total} onPage={list.setPage} />
    </section>
  );
}
