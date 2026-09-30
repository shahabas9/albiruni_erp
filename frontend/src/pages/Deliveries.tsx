import { useCallback, useState } from "react";
import { Link } from "react-router-dom";
import { fetchDeliveries } from "../api/sales";
import { Pager, SearchBox } from "../crm/ui";
import { useAppData } from "../data/AppDataProvider";
import { dayDate, docStatusClass } from "../lib/format";
import { PAGE_SIZE, usePaged } from "../lib/usePaged";

export function Deliveries() {
  const { version } = useAppData();
  const [search, setSearch] = useState("");
  const onSearch = useCallback((q: string) => setSearch(q), []);
  const list = usePaged((limit, offset) => fetchDeliveries({ q: search, limit, offset }), search, version);

  return (
    <section>
      <div className="page-head">
        <div className="eyebrow">Sales</div>
        <h1 className="page-title">Deliveries</h1>
        <p className="page-sub">Delivery notes for goods sent out. Each one took its goods out of stock; record new ones from the order.</p>
      </div>
      <div className="toolbar">
        <div />
        <SearchBox value={search} onChange={onSearch} placeholder="DN no., order, customer or vehicle" />
      </div>
      {list.error && <div className="error-banner">{list.error}</div>}
      {!list.loading && list.total === 0 && (
        <div className="card" style={{ textAlign: "center", color: "var(--ink-dim)" }}>
          {search ? "No deliveries match." : "No deliveries yet. Open a confirmed order and choose Deliver."}
        </div>
      )}
      {list.rows.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Delivery note</th>
                <th>Date</th>
                <th>Customer</th>
                <th>Order</th>
                <th>Goods</th>
                <th>Vehicle</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {list.rows.map((d) => (
                <tr key={d.id}>
                  <td className="mono">{d.number}</td>
                  <td>{dayDate(d.delivery_date)}</td>
                  <td>{d.customer_name}</td>
                  <td>
                    <Link className="link-btn mono" style={{ padding: 0 }} to={`/sales/orders/${d.order_id}`}>
                      {d.order_number}
                    </Link>
                  </td>
                  <td>{d.lines.map((l) => `${l.qty} ${l.uom} ${l.description}`).join(", ")}</td>
                  <td className="mono">{d.vehicle_no || "—"}</td>
                  <td>
                    <span className={`badge ${docStatusClass(d.status)}`}>{d.status}</span>
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
