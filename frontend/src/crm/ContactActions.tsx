import { useState } from "react";
import { createActivity, type ActivityType } from "../api/client";
import { Icon } from "../components/Icon";
import { useAppData } from "../data/AppDataProvider";
import { telHref, whatsappHref } from "../lib/phone";
import { ErrorNote, Modal } from "./ui";

type Target = { lead_id?: string; customer_id?: string; opportunity_id?: string };

const OUTCOMES: Record<"Call" | "WhatsApp", string[]> = {
  Call: ["Connected", "No answer", "Busy", "Call back later", "Wrong number"],
  WhatsApp: ["Message sent", "Replied", "Shared price list", "Shared quotation"],
};

/**
 * Call / WhatsApp buttons for a phone number. Opening either one then asks
 * how it went and logs it as a completed activity, so calls made from the
 * phone still show up in the CRM.
 */
export function ContactActions({
  phone,
  name,
  target,
  onLogged,
}: {
  phone: string;
  name: string;
  target: Target;
  onLogged?: () => void;
}) {
  const { can } = useAppData();
  const [logging, setLogging] = useState<"Call" | "WhatsApp" | null>(null);
  if (!phone.trim()) return null;
  const wa = whatsappHref(phone);
  const canLog = can("crm.activity.write");

  return (
    <span className="contact-actions" onClick={(e) => e.stopPropagation()}>
      <a className="icon-link" href={telHref(phone)} title={`Call ${name} (${phone})`} aria-label={`Call ${name}`} onClick={() => canLog && setLogging("Call")}>
        <Icon name="phone" size={16} />
      </a>
      {wa && (
        <a
          className="icon-link whatsapp"
          href={wa}
          target="_blank"
          rel="noreferrer"
          title={`WhatsApp ${name}`}
          aria-label={`WhatsApp ${name}`}
          onClick={() => canLog && setLogging("WhatsApp")}
        >
          <Icon name="whatsapp" size={16} />
        </a>
      )}
      {logging && (
        <LogContactModal
          kind={logging}
          name={name}
          target={target}
          onClose={() => setLogging(null)}
          onSaved={() => {
            setLogging(null);
            onLogged?.();
          }}
        />
      )}
    </span>
  );
}

function LogContactModal({
  kind,
  name,
  target,
  onClose,
  onSaved,
}: {
  kind: "Call" | "WhatsApp";
  name: string;
  target: Target;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [outcome, setOutcome] = useState(OUTCOMES[kind][0]!);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save() {
    setBusy(true);
    setError(null);
    try {
      await createActivity({
        type: kind as ActivityType,
        subject: `${kind === "Call" ? "Call" : "WhatsApp"} with ${name} — ${outcome}`,
        notes: note,
        done: true,
        ...target,
      });
      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't log it.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      title={kind === "Call" ? `How did the call with ${name} go?` : `WhatsApp with ${name}`}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="ghost-btn" onClick={onClose}>
            Skip
          </button>
          <button type="button" className="primary-btn" disabled={busy} onClick={save}>
            {busy ? "Logging…" : "Log it"}
          </button>
        </>
      }
    >
      <ErrorNote message={error} />
      <div className="fields">
        <div className="field full">
          Outcome
          <div className="reason-chips outcome">
            {OUTCOMES[kind].map((o) => (
              <button type="button" key={o} className={outcome === o ? "on" : ""} onClick={() => setOutcome(o)}>
                {o}
              </button>
            ))}
          </div>
        </div>
        <label className="field full">
          Note (optional)
          <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. Wants 200 boxes by March" autoFocus />
        </label>
      </div>
      <p className="card-note" style={{ marginBottom: 0 }}>
        Logged as a completed {kind === "Call" ? "call" : "WhatsApp"} — it counts as activity on the record.
      </p>
    </Modal>
  );
}
