import { useCallback, useEffect, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { ApiError } from "../api/client";
import {
  cancelDelivery,
  cancelOrder,
  confirmOrder,
  deleteOrder,
  fetchDeliveries,
  fetchInvoices,
  fetchOrder,
  fetchOrderTimeline,
  type DeliveryNote,
  type Invoice,
  type SalesOrder,
  setOrderSalesperson,
} from "../api/sales";
import { SalespersonField } from "../sales/SalespersonField";
import { Timeline } from "../crm/Timeline";
import { ErrorNote } from "../crm/ui";
import { useAppData } from "../data/AppDataProvider";
import { dateTime, dayDate, docStatusClass } from "../lib/format";
import { DeliverModal } from "../sales/DeliverModal";
import { InvoiceModal } from "../sales/InvoiceModal";
import { DocLinesTable } from "../sales/DocLinesTable";
import { DocTotals } from "../sales/DocTotals";
import { ReasonModal } from "../sales/ReasonModal";

export function OrderPage() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const { can } = useAppData();
  const [order, setOrder] = useState<SalesOrder | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [delivering, setDelivering] = useState(false);
  const [deliveries, setDeliveries] = useState<DeliveryNote[]>([]);
  const [undoing, setUndoing] = useState<DeliveryNote | null>(null);
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [invoicing, setInvoicing] = useState(false);
  const [changes, setChanges] = useState(0);
  const warnings = ((location.state as { warnings?: string[] } | null)?.warnings ?? []).filter(Boolean);

  const load = useCallback(async () => {
    try {
      const [o, d, inv] = await Promise.all([
        fetchOrder(id),
        fetchDeliveries({ order_id: id, limit: 100 }),
        can("sales.invoice.read") ? fetchInvoices({ order_id: id, limit: 100 }) : Promise.resolve({ rows: [] as Invoice[], total: 0 }),
      ]);
      setOrder(o);
      setDeliveries(d.rows);
      setInvoices(inv.rows);
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't load this order.");
    }
  }, [id, can]);

  useEffect(() => {
    void load();
  }, [load, changes]);

  if (!order) {
    return (
      <section>
        <Link to="/sales/orders" className="back-link">
          ← Sales orders
        </Link>
        <ErrorNote message={error} />
        {!error && <p className="card-note">Loading…</p>}
      </section>
    );
  }

  const canWrite = can("sales.order.write");
  const untouched = order.lines.every((l) => !l.delivered_qty && !l.invoiced_qty);
  const goodsLineIds = new Set(order.lines.filter((l) => l.item_kind === "goods").map((l) => l.id));
  const toDeliver = order.lines.some((l) => goodsLineIds.has(l.id) && l.qty > l.delivered_qty);
  const canDeliver = can("sales.delivery.write") && ["Confirmed", "Partly delivered"].includes(order.status) && toDeliver;
  const canInvoice =
    can("sales.invoice.write") && ["Confirmed", "Partly delivered", "Delivered"].includes(order.status) && order.lines.some((l) => l.qty > l.invoiced_qty);

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
      <Link to="/sales/orders" className="back-link">
        ← Sales orders
      </Link>
      <div className="page-head">
        <div>
          <div className="eyebrow">Sales order</div>
          <h1 className="page-title mono">{order.number}</h1>
          <p className="page-sub">
            <span className={`badge ${docStatusClass(order.status)}`}>{order.status}</span>{" "}
            {order.status !== "Draft" && order.status !== "Cancelled" && (
              <span className={`badge ${docStatusClass(order.invoice_status)}`}>{order.invoice_status}</span>
            )}{" "}
            <Link to={`/customers/${order.customer_id}`}>{order.customer_name}</Link> · {dayDate(order.order_date)}
            {order.customer_po && ` · PO ${order.customer_po}`}
            {order.quotation_number && ` · from ${order.quotation_number}`}
          </p>
        </div>
        {(canWrite || canDeliver || canInvoice) && (
          <div className="head-actions">
            {canInvoice && (
              <button className={canDeliver ? "ghost-btn" : "primary-btn"} disabled={busy} onClick={() => setInvoicing(true)}>
                Create invoice
              </button>
            )}
            {canDeliver && (
              <button className="primary-btn" disabled={busy} onClick={() => setDelivering(true)}>
                Deliver
              </button>
            )}
            {canWrite && order.status === "Draft" && (
              <>
                <button className="ghost-btn" disabled={busy} onClick={() => navigate(`/sales/orders/${order.id}/edit`)}>
                  Edit
                </button>
                <button
                  className="ghost-btn"
                  disabled={busy}
                  onClick={() => window.confirm(`Delete draft ${order.number}?`) && act(async () => (await deleteOrder(order.id), navigate("/sales/orders")))}
                >
                  Delete
                </button>
                <button className="primary-btn" disabled={busy} onClick={() => act(() => confirmOrder(order.id))}>
                  {busy ? "Working…" : "Confirm order"}
                </button>
              </>
            )}
            {canWrite && order.status !== "Draft" && order.status !== "Cancelled" && untouched && (
              <button className="danger-btn" disabled={busy} onClick={() => setCancelling(true)}>
                Cancel order
              </button>
            )}
          </div>
        )}
      </div>

      <ErrorNote message={error} />
      {warnings.length > 0 && order.status === "Draft" && <div className="notice-banner">{warnings.join(" ")}</div>}
      {order.status === "Draft" && order.needs_approval && (
        <div className="notice-banner">
          This order has a discount over the limit or a price below list, so a manager (sales.quotation.approve) has to confirm it.
        </div>
      )}
      {order.status === "Cancelled" && <div className="error-banner">Cancelled — {order.cancel_reason}</div>}

      <div className="doc-grid">
        <div className="card">
          <DocLinesTable lines={order.lines} progress={order.status !== "Draft"} />
          <DocTotals doc={order} subtotal={order.subtotal} discountPct={order.discount_pct} />
        </div>
        <div>
          <div className="card doc-facts">
            <div>
              <span>Bill to</span>
              <p>
                {order.customer_name}
                {order.customer_gstin && <small className="mono">GSTIN {order.customer_gstin}</small>}
                {order.billing_address && <small>{order.billing_address}</small>}
              </p>
            </div>
            {order.shipping_address && order.shipping_address !== order.billing_address && (
              <div>
                <span>Ship to</span>
                <p>{order.shipping_address}</p>
              </div>
            )}
            <div>
              <span>Place of supply</span>
              <p>{order.place_of_supply || "—"}</p>
            </div>
            <SalespersonField
              id={order.salesperson_id}
              name={order.salesperson_name}
              onSave={
                can("sales.order.write") && order.status !== "Cancelled"
                  ? async (userId) => setOrder(await setOrderSalesperson(order.id, userId))
                  : undefined
              }
            />
            <div>
              <span>Created</span>
              <p>
                {dateTime(order.created_at)}
                {order.created_by_name && ` by ${order.created_by_name}`}
              </p>
            </div>
            {order.confirmed_at && (
              <div>
                <span>Confirmed</span>
                <p>
                  {dateTime(order.confirmed_at)}
                  {order.approved_by_name && ` · discount approved by ${order.approved_by_name}`}
                </p>
              </div>
            )}
            {order.notes && (
              <div>
                <span>Notes</span>
                <p>{order.notes}</p>
              </div>
            )}
          </div>
          {order.status !== "Draft" && can("sales.invoice.read") && (
            <div className="card">
              <div className="card-head">
                <span className="card-title">Invoices</span>
              </div>
              {invoices.length === 0 && <p className="card-note">Not invoiced yet.</p>}
              <div className="mini-docs">
                {invoices.map((i) => (
                  <div className="row" key={i.id}>
                    <div>
                      <Link className="mono" to={`/sales/invoices/${i.id}`}>
                        {i.number ?? "Draft invoice"}
                      </Link>
                      <small>
                        {i.lines.map((l) => `${l.qty} ${l.uom} ${l.description}`).join(", ")} · ₹{i.grand_total.toLocaleString("en-IN")}
                      </small>
                    </div>
                    <span className={`badge ${docStatusClass(i.payment_status)}`}>{i.payment_status}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
          {order.status !== "Draft" && (
            <div className="card">
              <div className="card-head">
                <span className="card-title">Deliveries</span>
              </div>
              {deliveries.length === 0 && <p className="card-note">Nothing delivered yet.</p>}
              <div className="mini-docs">
                {deliveries.map((d) => (
                  <div className={`row${d.status === "Cancelled" ? " cancelled" : ""}`} key={d.id}>
                    <div>
                      <b className="mono">{d.number}</b> · {dayDate(d.delivery_date)}
                      <small>{d.lines.map((l) => `${l.qty} ${l.uom} ${l.description}`).join(", ")}</small>
                      {d.vehicle_no && <small>Vehicle {d.vehicle_no}</small>}
                      {d.status === "Cancelled" && <small>Cancelled — {d.cancel_reason}</small>}
                    </div>
                    <div style={{ display: "flex", gap: 6 }}>
                      <a className="ghost-btn sm" href={`/print/delivery/${d.id}`} target="_blank" rel="noreferrer">
                        Challan
                      </a>
                      {d.status === "Delivered" && can("sales.delivery.write") && (
                        <button className="ghost-btn sm" onClick={() => setUndoing(d)}>
                          Cancel
                        </button>
                      )}
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
            <Timeline load={() => fetchOrderTimeline(order.id)} version={changes} />
          </div>
        </div>
      </div>

      {delivering && (
        <DeliverModal
          order={order}
          goodsLineIds={goodsLineIds}
          onClose={() => setDelivering(false)}
          onDone={() => {
            setDelivering(false);
            setChanges((n) => n + 1);
          }}
        />
      )}
      {invoicing && <InvoiceModal order={order} onClose={() => setInvoicing(false)} />}
      {undoing && (
        <ReasonModal
          title={`Cancel delivery ${undoing.number}?`}
          label="Why? The goods go back into stock."
          action="Cancel delivery"
          onClose={() => setUndoing(null)}
          onConfirm={async (reason) => {
            await cancelDelivery(undoing.id, reason);
            setUndoing(null);
            setChanges((n) => n + 1);
          }}
        />
      )}
      {cancelling && (
        <ReasonModal
          title={`Cancel ${order.number}?`}
          label="Why is it being cancelled?"
          action="Cancel order"
          onClose={() => setCancelling(false)}
          onConfirm={async (reason) => {
            await cancelOrder(order.id, reason);
            setCancelling(false);
            setChanges((n) => n + 1);
          }}
        />
      )}
    </section>
  );
}
