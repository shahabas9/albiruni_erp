import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ApiError, fetchSalesItems, type Item } from "../api/client";
import { createOrder, fetchOrder, updateOrder, type SalesOrder } from "../api/sales";
import { CustomerPicker } from "../components/CustomerPicker";
import { ErrorNote } from "../crm/ui";
import { inr, todayIso } from "../lib/format";
import { blankLine, editLine, estimate, LineItemsEditor, linePayload, useAgreedPrices, type EditLine } from "../sales/LineItemsEditor";

/** New order (/sales/orders/new) or a draft being edited (/sales/orders/:id/edit). */
export function OrderEditor() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [items, setItems] = useState<Item[] | null>(null);
  const [existing, setExisting] = useState<SalesOrder | null>(null);
  const [customerId, setCustomerId] = useState("");
  const [lines, setLines] = useState<EditLine[]>([]);
  const [discount, setDiscount] = useState("0");
  const [po, setPo] = useState("");
  const [notes, setNotes] = useState("");
  const [orderDate, setOrderDate] = useState(todayIso());
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const prices = useAgreedPrices(customerId);

  useEffect(() => {
    let live = true;
    Promise.all([fetchSalesItems(), id ? fetchOrder(id) : Promise.resolve(null)])
      .then(([its, order]) => {
        if (!live) return;
        setItems(its);
        if (order) {
          setExisting(order);
          setCustomerId(order.customer_id);
          setLines(order.lines.map(editLine));
          setDiscount(String(order.discount_pct));
          setPo(order.customer_po);
          setNotes(order.notes);
          setOrderDate(order.order_date);
        } else {
          setLines([blankLine(its)]);
        }
      })
      .catch((err) => live && setError(err instanceof ApiError ? err.message : "Couldn't load."));
    return () => {
      live = false;
    };
  }, [id]);

  if (!items) {
    return (
      <section>
        <ErrorNote message={error} />
        {!error && <p className="card-note">Loading…</p>}
      </section>
    );
  }
  if (existing && existing.status !== "Draft") {
    return (
      <section>
        <p className="card-note">
          {existing.number} is {existing.status.toLowerCase()} and can't be edited. <Link to={`/sales/orders/${existing.id}`}>Back to the order</Link>
        </p>
      </section>
    );
  }

  const est = estimate(lines, items, Number(discount), prices);
  const valid = customerId && lines.length > 0 && lines.every((l) => l.item_id && Number(l.qty) > 0);

  async function save() {
    setSaving(true);
    setError(null);
    const body = {
      lines: lines.map(linePayload),
      discount_pct: Number(discount) || 0,
      customer_po: po,
      notes,
      order_date: orderDate,
    };
    try {
      const saved = existing ? await updateOrder(existing.id, body) : await createOrder({ customer_id: customerId, ...body });
      navigate(`/sales/orders/${saved.id}`, { state: { warnings: saved.warnings } });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't save the order.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <section>
      <Link to={existing ? `/sales/orders/${existing.id}` : "/sales/orders"} className="back-link">
        ← {existing ? existing.number : "Sales orders"}
      </Link>
      <div className="page-head">
        <h1 className="page-title">{existing ? `Edit ${existing.number}` : "New sales order"}</h1>
        <p className="page-sub">Saved as a draft. Nothing is committed until you confirm it.</p>
      </div>

      <div className="card form-card">
        <div className="field-grid">
          {existing ? (
            <div className="field full">
              <span>Customer</span>
              <span className="static">{existing.customer_name}</span>
            </div>
          ) : (
            <CustomerPicker value={customerId} onChange={setCustomerId} />
          )}
          <label className="field">
            <span>Order date</span>
            <input type="date" value={orderDate} onChange={(e) => setOrderDate(e.target.value)} />
          </label>
          <label className="field">
            <span>Customer's PO number</span>
            <input value={po} maxLength={60} onChange={(e) => setPo(e.target.value)} />
          </label>
          <label className="field">
            <span>Discount %</span>
            <input type="number" min={0} max={100} step="0.5" value={discount} onChange={(e) => setDiscount(e.target.value)} />
          </label>
        </div>
        <LineItemsEditor lines={lines} items={items} onChange={setLines} prices={prices} />
        <label className="field full">
          <span>Notes</span>
          <textarea rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} />
        </label>
        <div className="quote-total">
          <span>
            Estimated {inr(est.taxable)} + GST {inr(est.gst)} (worked out exactly on save)
          </span>
          <b className="num">{inr(est.total)}</b>
        </div>
        <ErrorNote message={error} />
        <div className="form-actions">
          <button className="primary-btn" disabled={!valid || saving} onClick={save}>
            {saving ? "Saving…" : "Save draft"}
          </button>
          <Link className="secondary-btn" to={existing ? `/sales/orders/${existing.id}` : "/sales/orders"}>
            Cancel
          </Link>
        </div>
      </div>
    </section>
  );
}
