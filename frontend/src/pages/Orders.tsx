import { useCallback, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { fetchOrders } from "../api/sales";
import { Pager, SearchBox } from "../crm/ui";
import { useAppData } from "../data/AppDataProvider";
import { dayDate, docStatusClass, inr } from "../lib/format";
import { PAGE_SIZE, usePaged } from "../lib/usePaged";

const FILTERS = [
  { key: "", label: "All" },
  { key: "Draft", label: "Drafts" },
  { key: "open", label: "Open" },
  { key: "Delivered", label: "Delivered" },
  { key: "Cancelled", label: "Cancelled" },
];

export function Orders() {
  const { can, version } = useAppData();
  const navigate = useNavigate();
  const [status, setStatus] = useState("");
  const [search, setSearch] = useState("");
  const onSearch = useCallback((q: string) => setSearch(q), []);
  const list = usePaged((limit, offset) => fetchOrders({ status, q: search, limit, offset }), `${status}|${search}`, version);

  return (
    <section>
      <div className="page-head">
        <div className="eyebrow">Sales</div>
        <h1 className="page-title">Sales orders</h1>
        <p className="page-sub">What customers have agreed to buy — from a quotation or entered directly. Confirmed orders are delivered and invoiced from here.</p>
      </div>

      <div className="toolbar">
        <div className="filters">
          {FILTERS.map((f) => (
            <button key={f.key} className={status === f.key ? "on" : ""} onClick={() => setStatus(f.key)}>
              {f.label}
            </button>
          ))}
        </div>
        <SearchBox value={search} onChange={onSearch} placeholder="Order no., customer or PO" />
        {can("sales.order.write") && (
          <button className="primary-btn" onClick={() => navigate("/sales/orders/new")}>
            + New order
          </button>
        )}
      </div>

      {list.error && <div className="error-banner">{list.error}</div>}
      {!list.loading && list.total === 0 && (
        <div className="card" style={{ textAlign: "center", color: "var(--ink-dim)" }}>
          {status || search ? "No orders match this filter." : "No orders yet. Turn an accepted quotation into one, or add one directly."}
        </div>
      )}
      {list.rows.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Order</th>
                <th>Date</th>
                <th>Customer</th>
                <th>Customer PO</th>
                <th className="num">Total</th>
                <th>Status</th>
                <th>Invoicing</th>
              </tr>
            </thead>
            <tbody>
              {list.rows.map((o) => (
                <tr key={o.id}>
                  <td>
                    <Link className="link-btn mono" style={{ padding: 0 }} to={`/sales/orders/${o.id}`}>
                      {o.number}
                    </Link>
                  </td>
                  <td>{dayDate(o.order_date)}</td>
                  <td>{o.customer_name}</td>
                  <td className="mono">{o.customer_po || "—"}</td>
                  <td className="num">{inr(o.grand_total)}</td>
                  <td>
                    <span className={`badge ${docStatusClass(o.status)}`}>{o.status}</span>
                    {o.status === "Draft" && o.needs_approval && <span className="badge status-pending">Needs approval</span>}
                  </td>
                  <td>{o.status === "Draft" || o.status === "Cancelled" ? "—" : <span className={`badge ${docStatusClass(o.invoice_status)}`}>{o.invoice_status}</span>}</td>
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
