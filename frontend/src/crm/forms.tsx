import { useState, type FormEvent } from "react";
import {
  ACTIVITY_KINDS,
  ApiError,
  crm,
  type ActivityKind,
  type Assignee,
  type CreateQuotationResult,
  type Item,
  type CrmLead as Lead,
  type CrmOpportunity as Opportunity,
} from "../api/client";
import { Icon } from "../components/Icon";
import { inr, toLocalInput } from "../lib/format";
import { ErrorNote, Modal } from "./ui";

const LEAD_SOURCES = ["Walk-in", "Referral", "Phone", "Website", "Existing customer", "Other"];

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

export function NewLeadModal({
  assignees,
  canAssign,
  currentUserId,
  onClose,
  onSaved,
}: {
  assignees: Assignee[];
  canAssign: boolean;
  currentUserId: string | undefined;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [f, setF] = useState({ name: "", organization: "", phone: "", email: "", source: "Walk-in" });
  const [ownerId, setOwnerId] = useState<string | null>(currentUserId ?? null);
  const { busy, error, submit } = useSubmit(() => crm.createLead({ ...f, owner_id: ownerId }), onSaved);
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });

  return (
    <Modal title="New lead" onClose={onClose} footer={<Footer onClose={onClose} busy={busy} label="Create lead" formId="lead-form" />}>
      <ErrorNote message={error} />
      <form id="lead-form" className="fields" onSubmit={submit}>
        <label className="field">
          Contact name
          <input required autoFocus value={f.name} onChange={set("name")} />
        </label>
        <label className="field">
          Business
          <input value={f.organization} onChange={set("organization")} placeholder="Becomes the customer on convert" />
        </label>
        <label className="field">
          Phone
          <input value={f.phone} onChange={set("phone")} inputMode="tel" />
        </label>
        <label className="field">
          Email
          <input type="email" value={f.email} onChange={set("email")} />
        </label>
        <label className="field">
          Source
          <select value={f.source} onChange={set("source")}>
            {LEAD_SOURCES.map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
        </label>
        <label className="field">
          Owner
          <select value={ownerId ?? ""} onChange={(e) => setOwnerId(e.target.value || null)}>
            <option value="">Unassigned</option>
            {assignees
              .filter((a) => canAssign || a.id === currentUserId)
              .map((a) => (
                <option key={a.id} value={a.id}>
                  {a.display_name}
                  {a.id === currentUserId ? " (me)" : ""}
                </option>
              ))}
          </select>
        </label>
      </form>
    </Modal>
  );
}

export function NewOpportunityModal({
  assignees,
  canAssign,
  currentUserId,
  onClose,
  onSaved,
}: {
  assignees: Assignee[];
  canAssign: boolean;
  currentUserId: string | undefined;
  onClose: () => void;
  onSaved: (opp: Opportunity) => void;
}) {
  const [f, setF] = useState({ title: "", customer_name: "", expected_value: "", expected_close: "" });
  const [ownerId, setOwnerId] = useState<string | null>(currentUserId ?? null);
  const { busy, error, submit } = useSubmit(
    () =>
      crm.createOpportunity({
        title: f.title,
        customer_name: f.customer_name,
        expected_value: Number(f.expected_value) || 0,
        expected_close: f.expected_close || null,
        owner_id: ownerId,
      }),
    onSaved,
  );
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });

  return (
    <Modal
      title="New opportunity"
      onClose={onClose}
      footer={<Footer onClose={onClose} busy={busy} label="Create opportunity" formId="opp-form" />}
    >
      <ErrorNote message={error} />
      <form id="opp-form" className="fields" onSubmit={submit}>
        <label className="field full">
          Title
          <input required autoFocus value={f.title} onChange={set("title")} placeholder="e.g. Coastal Traders — monsoon stock" />
        </label>
        <label className="field full">
          Customer
          <input required value={f.customer_name} onChange={set("customer_name")} placeholder="Existing or new customer name" />
        </label>
        <label className="field">
          Expected value (₹)
          <input type="number" min={0} step="1" value={f.expected_value} onChange={set("expected_value")} />
        </label>
        <label className="field">
          Expected close
          <input type="date" value={f.expected_close} onChange={set("expected_close")} />
        </label>
        <label className="field full">
          Owner
          <select value={ownerId ?? ""} onChange={(e) => setOwnerId(e.target.value || null)}>
            <option value="">Unassigned</option>
            {assignees
              .filter((a) => canAssign || a.id === currentUserId)
              .map((a) => (
                <option key={a.id} value={a.id}>
                  {a.display_name}
                  {a.id === currentUserId ? " (me)" : ""}
                </option>
              ))}
          </select>
        </label>
      </form>
    </Modal>
  );
}

export function ConvertLeadModal({
  lead,
  onClose,
  onSaved,
}: {
  lead: Lead;
  onClose: () => void;
  onSaved: (opp: Opportunity) => void;
}) {
  const business = lead.organization || lead.name;
  const [f, setF] = useState({ title: `${business} — new deal`, expected_value: "", expected_close: "" });
  const { busy, error, submit } = useSubmit(
    () =>
      crm.convertLead(lead.id, {
        title: f.title,
        expected_value: Number(f.expected_value) || 0,
        expected_close: f.expected_close || null,
      }),
    onSaved,
  );
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });

  return (
    <Modal
      title={`Convert ${lead.name}`}
      onClose={onClose}
      footer={<Footer onClose={onClose} busy={busy} label="Convert to opportunity" formId="convert-form" />}
    >
      <p className="card-note" style={{ marginTop: 0 }}>
        Creates (or reuses) the customer <b>{business}</b> and opens an opportunity owned by{" "}
        <b>{lead.owner_name ?? "nobody yet"}</b>. Open follow-ups move with it.
      </p>
      <ErrorNote message={error} />
      <form id="convert-form" className="fields" onSubmit={submit}>
        <label className="field full">
          Opportunity title
          <input required value={f.title} onChange={set("title")} />
        </label>
        <label className="field">
          Expected value (₹)
          <input type="number" min={0} value={f.expected_value} onChange={set("expected_value")} />
        </label>
        <label className="field">
          Expected close
          <input type="date" value={f.expected_close} onChange={set("expected_close")} />
        </label>
      </form>
    </Modal>
  );
}

export function FollowUpModal({
  target,
  onClose,
  onSaved,
}: {
  target: { lead_id?: string; opportunity_id?: string; name: string };
  onClose: () => void;
  onSaved: () => void;
}) {
  const [kind, setKind] = useState<ActivityKind>("Call");
  const [subject, setSubject] = useState("");
  const [due, setDue] = useState(() => {
    const tomorrow = new Date();
    tomorrow.setDate(tomorrow.getDate() + 1);
    tomorrow.setHours(10, 0, 0, 0);
    return toLocalInput(tomorrow);
  });
  const { busy, error, submit } = useSubmit(
    () =>
      crm.createActivity({
        kind,
        subject,
        due_at: new Date(due).toISOString(),
        lead_id: target.lead_id,
        opportunity_id: target.opportunity_id,
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
          <select value={kind} onChange={(e) => setKind(e.target.value as ActivityKind)}>
            {ACTIVITY_KINDS.map((k) => (
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
  const priceOf = (name: string) => items.find((i) => i.name === name)?.unit_price ?? 0;
  const subtotal = lines.reduce((s, l) => s + priceOf(l.item_name) * (Number(l.qty) || 0), 0);
  const total = subtotal * (1 - (Number(discount) || 0) / 100);

  const { busy, error, submit } = useSubmit(
    () =>
      crm.quoteOpportunity(opportunity.id, {
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
        <span>Estimated total (server re-prices on save)</span>
        <b className="num">{inr(total)}</b>
      </div>
      <button type="submit" className="primary-btn" disabled={busy} style={{ alignSelf: "flex-end" }}>
        <Icon name="file" size={16} /> {busy ? "Creating…" : `Create quotation for ${opportunity.customer_name}`}
      </button>
    </form>
  );
}
