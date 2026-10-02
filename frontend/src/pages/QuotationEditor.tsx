import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ApiError, fetchSalesItems, type Item, type Quotation } from "../api/client";
import { createQuotation, fetchQuotation, updateQuotation } from "../api/sales";
import { CustomerPicker } from "../components/CustomerPicker";
import { ErrorNote } from "../crm/ui";
import { inr, todayIso, taxLabel } from "../lib/format";
import { blankLine, editLine, estimate, LineItemsEditor, linePayload, useAgreedPrices, type EditLine } from "../sales/LineItemsEditor";

/** New quotation (/sales/quotations/new) or a draft being edited (/sales/quotations/:id/edit). */
export function QuotationEditor() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [items, setItems] = useState<Item[] | null>(null);
  const [existing, setExisting] = useState<Quotation | null>(null);
  const [customerId, setCustomerId] = useState("");
  const [lines, setLines] = useState<EditLine[]>([]);
  const [discount, setDiscount] = useState("0");
  const [validUntil, setValidUntil] = useState("");
  const [notes, setNotes] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const prices = useAgreedPrices(existing?.customer_id ?? customerId);

  useEffect(() => {
    let live = true;
    Promise.all([fetchSalesItems(), id ? fetchQuotation(id) : Promise.resolve(null)])
      .then(([its, q]) => {
        if (!live) return;
        setItems(its);
        if (q) {
          setExisting(q);
          setLines(q.lines.map(editLine));
          setDiscount(String(q.discount_pct));
          setValidUntil(q.valid_until ?? "");
          setNotes(q.notes);
        } else {
          setLines([blankLine(its)]);
        }
      })
      .catch((err) => live && setError(err instanceof ApiError ? err.message : "Couldn't load."));
    return () => {
      live = false;
    };
  }, [id]);

  if (!items) return <section>{error ? <ErrorNote message={error} /> : <p className="card-note">Loading…</p>}</section>;
  if (existing && !["Draft", "Pending approval"].includes(existing.status)) {
    return (
      <section>
        <p className="card-note">
          {existing.number} is {existing.status.toLowerCase()} and can't be edited. <Link to="/sales">Back to quotations</Link>
        </p>
      </section>
    );
  }

  const est = estimate(lines, items, Number(discount), prices);
  const valid = (existing || customerId) && lines.length > 0 && lines.every((l) => l.item_id && Number(l.qty) > 0);

  async function save() {
    setSaving(true);
    setError(null);
    const body = {
      lines: lines.map(linePayload),
      discount_pct: Number(discount) || 0,
      notes,
      ...(validUntil ? { valid_until: validUntil } : {}),
    };
    try {
      if (existing) await updateQuotation(existing.id, body);
      else await createQuotation({ customer_id: customerId, ...body });
      navigate("/sales");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't save the quotation.");
      setSaving(false);
    }
  }

  return (
    <section>
      <Link to="/sales" className="back-link">
        ← Quotations
      </Link>
      <div className="page-head">
        <h1 className="page-title">{existing ? `Edit ${existing.number}` : "New quotation"}</h1>
        <p className="page-sub">A discount over the limit or a price below list goes to a manager for approval before it can be sent.</p>
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
            <span>Valid until</span>
            <input type="date" value={validUntil} min={todayIso()} onChange={(e) => setValidUntil(e.target.value)} placeholder="Company default" />
          </label>
          <label className="field">
            <span>Discount %</span>
            <input type="number" min={0} max={100} step="0.5" value={discount} onChange={(e) => setDiscount(e.target.value)} />
          </label>
        </div>
        <LineItemsEditor lines={lines} items={items} onChange={setLines} prices={prices} />
        <label className="field full">
          <span>Notes (printed on the quotation)</span>
          <textarea rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="e.g. Delivery within 7 days of order" />
        </label>
        <div className="quote-total">
          <span>
            Estimated {inr(est.taxable)} + {taxLabel()} {inr(est.gst)} (worked out exactly on save)
          </span>
          <b className="num">{inr(est.total)}</b>
        </div>
        <ErrorNote message={error} />
        <div className="form-actions">
          <button className="primary-btn" disabled={!valid || saving} onClick={save}>
            {saving ? "Saving…" : existing ? "Save changes" : "Save quotation"}
          </button>
          <Link className="secondary-btn" to="/sales">
            Cancel
          </Link>
        </div>
      </div>
    </section>
  );
}
