import { useState, type FormEvent } from "react";
import {
  ACTIVITY_TYPES,
  ApiError,
  LOST_REASONS,
  createActivity,
  quoteOpportunity,
  type ActivityType,
  type CreateQuotationResult,
  type Item,
  type Opportunity,
} from "../api/client";
import { Icon } from "../components/Icon";
import { inr, toLocalInput } from "../lib/format";
import { ErrorNote, Modal } from "./ui";

function errorText(err: unknown): string {
  return err instanceof ApiError ? err.message : "Could not reach the Albiruni API.";
}

/** Shared submit plumbing: busy flag, error message, and close-on-success. */
function useSubmit<T>(action: () => Promise<T>, onDone: (result: T) => void) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const submit = async (e?: FormEvent) => {
    e?.preventDefault();
    setBusy(true);
    setError(null);
    try {
      onDone(await action());
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };
  return { busy, error, submit };
}

function Footer({ onClose, busy, label, formId }: { onClose: () => void; busy: boolean; label: string; formId: string }) {
  return (
    <>
      <button type="button" className="ghost-btn" onClick={onClose}>
        Cancel
      </button>
      <button type="submit" form={formId} className="primary-btn" disabled={busy}>
        {busy ? "Saving…" : label}
      </button>
    </>
  );
}

export function FollowUpModal({
  target,
  onClose,
  onSaved,
}: {
  target: { lead_id?: string; opportunity_id?: string; customer_id?: string; name: string };
  onClose: () => void;
  onSaved: () => void;
}) {
  const [kind, setKind] = useState<ActivityType>("Call");
  const [subject, setSubject] = useState("");
  const [due, setDue] = useState(() => {
    const tomorrow = new Date();
    tomorrow.setDate(tomorrow.getDate() + 1);
    tomorrow.setHours(10, 0, 0, 0);
    return toLocalInput(tomorrow);
  });
  const { busy, error, submit } = useSubmit(
    () =>
      createActivity({
        type: kind,
        subject,
        due_at: new Date(due).toISOString(),
        lead_id: target.lead_id,
        opportunity_id: target.opportunity_id,
        customer_id: target.customer_id,
      }),
    onSaved,
  );

  return (
    <Modal
      title={`Follow-up · ${target.name}`}
      onClose={onClose}
      footer={<Footer onClose={onClose} busy={busy} label="Schedule" formId="fu-form" />}
    >
      <ErrorNote message={error} />
      <form id="fu-form" className="fields" onSubmit={submit}>
        <label className="field">
          Type
          <select value={kind} onChange={(e) => setKind(e.target.value as ActivityType)}>
            {ACTIVITY_TYPES.map((k) => (
              <option key={k}>{k}</option>
            ))}
          </select>
        </label>
        <label className="field">
          Due
          <input type="datetime-local" required value={due} onChange={(e) => setDue(e.target.value)} />
        </label>
        <label className="field full">
          Subject
          <input required autoFocus value={subject} onChange={(e) => setSubject(e.target.value)} placeholder="e.g. Confirm delivery dates" />
        </label>
      </form>
    </Modal>
  );
}

interface DraftLine {
  item_name: string;
  qty: string;
}

/** Opportunity -> Quotation. The customer is fixed by the opportunity. */
export function QuoteForm({
  opportunity,
  items,
  onCreated,
}: {
  opportunity: Opportunity;
  items: Item[];
  onCreated: (result: CreateQuotationResult) => void;
}) {
  const [lines, setLines] = useState<DraftLine[]>([{ item_name: items[0]?.name ?? "", qty: "1" }]);
  const [discount, setDiscount] = useState("0");
  const itemOf = (name: string) => items.find((i) => i.name === name);
  const factor = 1 - (Number(discount) || 0) / 100;
  const total = lines.reduce((s, l) => s + (itemOf(l.item_name)?.unit_price ?? 0) * (Number(l.qty) || 0) * factor, 0);
  const gst = lines.reduce(
    (s, l) => s + (itemOf(l.item_name)?.unit_price ?? 0) * (Number(l.qty) || 0) * factor * ((itemOf(l.item_name)?.gst_rate ?? 0) / 100),
    0,
  );

  const { busy, error, submit } = useSubmit(
    () =>
      quoteOpportunity(opportunity.id, {
        lines: lines.filter((l) => l.item_name && Number(l.qty) > 0).map((l) => ({ item_name: l.item_name, qty: Number(l.qty) })),
        discount_pct: Number(discount) || 0,
      }),
    (result) => {
      setLines([{ item_name: items[0]?.name ?? "", qty: "1" }]);
      setDiscount("0");
      onCreated(result);
    },
  );

  const update = (idx: number, patch: Partial<DraftLine>) =>
    setLines(lines.map((l, i) => (i === idx ? { ...l, ...patch } : l)));

  if (items.length === 0) {
    return <p className="card-note">No items in the price list yet — add items before quoting.</p>;
  }

  return (
    <form onSubmit={submit} className="line-editor">
      <ErrorNote message={error} />
      {lines.map((line, idx) => (
        <div className="line" key={idx}>
          <select value={line.item_name} onChange={(e) => update(idx, { item_name: e.target.value })} aria-label="Item">
            {items.map((i) => (
              <option key={i.id} value={i.name}>
                {i.name} · {inr(i.unit_price)}/{i.uom} · {i.stock_qty} in stock
              </option>
            ))}
          </select>
          <input
            type="number"
            min={1}
            step="1"
            value={line.qty}
            onChange={(e) => update(idx, { qty: e.target.value })}
            aria-label="Quantity"
          />
          <button
            type="button"
            className="icon-btn"
            aria-label="Remove line"
            disabled={lines.length === 1}
            onClick={() => setLines(lines.filter((_, i) => i !== idx))}
          >
            <Icon name="x" size={16} />
          </button>
        </div>
      ))}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
        <button type="button" className="ghost-btn sm" onClick={() => setLines([...lines, { item_name: items[0]!.name, qty: "1" }])}>
          <Icon name="plus" size={14} /> Add line
        </button>
        <label className="field" style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
          Discount %
          <input
            type="number"
            min={0}
            max={100}
            step="0.5"
            value={discount}
            onChange={(e) => setDiscount(e.target.value)}
            style={{ width: 80 }}
          />
        </label>
      </div>
      <div className="quote-total">
        <span>
          Estimated {inr(total)} + GST {inr(gst)} (worked out exactly on save)
        </span>
        <b className="num">{inr(Math.round(total + gst))}</b>
      </div>
      <button type="submit" className="primary-btn" disabled={busy} style={{ alignSelf: "flex-end" }}>
        <Icon name="file" size={16} /> {busy ? "Creating…" : `Create quotation for ${opportunity.customer_name}`}
      </button>
    </form>
  );
}

/** Asks why a deal was lost before it's marked Lost — the reason feeds the win/loss report. */
export function LostReasonModal({
  dealName,
  onClose,
  onConfirm,
}: {
  dealName: string;
  onClose: () => void;
  onConfirm: (reason: string) => Promise<void>;
}) {
  const [reason, setReason] = useState("");
  const { busy, error, submit } = useSubmit(() => onConfirm(reason.trim()), () => undefined);

  return (
    <Modal
      title={`Why was “${dealName}” lost?`}
      onClose={onClose}
      footer={<Footer onClose={onClose} busy={busy} label="Mark as lost" formId="lost-form" />}
    >
      <ErrorNote message={error} />
      <form id="lost-form" onSubmit={submit} className="fields">
        <div className="field full">
          Common reasons
          <div className="reason-chips">
            {LOST_REASONS.map((r) => (
              <button type="button" key={r} className={reason === r ? "on" : ""} onClick={() => setReason(r)}>
                {r}
              </button>
            ))}
          </div>
        </div>
        <label className="field full">
          Reason
          <input required value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Pick one above or type your own" />
        </label>
      </form>
    </Modal>
  );
}
