import { useCallback, useEffect, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { ApiError } from "../api/client";
import { cancelOrder, confirmOrder, deleteOrder, fetchOrder, fetchOrderTimeline, type SalesOrder } from "../api/sales";
import { Timeline } from "../crm/Timeline";
import { ErrorNote } from "../crm/ui";
import { useAppData } from "../data/AppDataProvider";
import { dateTime, dayDate, docStatusClass } from "../lib/format";
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
  const [changes, setChanges] = useState(0);
  const warnings = ((location.state as { warnings?: string[] } | null)?.warnings ?? []).filter(Boolean);

  const load = useCallback(async () => {
    try {
      setOrder(await fetchOrder(id));
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't load this order.");
    }
  }, [id]);

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
        {canWrite && (
          <div className="head-actions">
            {order.status === "Draft" && (
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
            {order.status !== "Draft" && order.status !== "Cancelled" && untouched && (
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
          <div className="card">
            <div className="card-head">
              <span className="card-title">History</span>
            </div>
            <Timeline load={() => fetchOrderTimeline(order.id)} version={changes} />
          </div>
        </div>
      </div>

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
