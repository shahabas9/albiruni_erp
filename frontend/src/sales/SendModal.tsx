import { useEffect, useState } from "react";
import { ApiError } from "../api/client";
import { fetchShareRecipients, shareDocument, type ShareKind, type ShareResult } from "../api/sales";
import { ErrorNote, Modal } from "../crm/ui";
import { dayDate } from "../lib/format";
import { internationalDigits } from "../lib/phone";

/** Send a customer a link to a document: by email, by WhatsApp, or copy it. */
export function SendModal({
  kind,
  id,
  customerId,
  title,
  period,
  onClose,
}: {
  kind: ShareKind;
  id: string;
  customerId: string;
  title: string;
  /** Statements only. */
  period?: { date_from: string; date_to: string };
  onClose: () => void;
}) {
  const [people, setPeople] = useState<{ name: string; email: string; phone: string }[]>([]);
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [result, setResult] = useState<ShareResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    fetchShareRecipients(customerId)
      .then((rows) => {
        setPeople(rows);
        setEmail(rows.find((r) => r.email)?.email ?? "");
        setPhone(rows.find((r) => r.phone)?.phone ?? "");
      })
      .catch(() => setPeople([]));
  }, [customerId]);

  async function run(how: "email" | "whatsapp" | "copy") {
    setBusy(true);
    setError(null);
    // Open the WhatsApp tab straight away (inside the click), so pop-up blockers allow it.
    const tab = how === "whatsapp" ? window.open("about:blank", "_blank") : null;
    try {
      const out = await shareDocument({ kind, id, ...(how === "email" ? { email } : {}), ...(period ?? {}) });
      setResult(out);
      if (how === "whatsapp") {
        const digits = internationalDigits(phone);
        const url = `https://wa.me/${digits ?? ""}?text=${out.whatsapp_text}`;
        if (tab) tab.location.href = url;
        else window.open(url, "_blank", "noopener");
      }
      if (how === "copy") {
        await navigator.clipboard?.writeText(out.url).catch(() => undefined);
        setCopied(true);
      }
    } catch (err) {
      tab?.close();
      setError(err instanceof ApiError ? err.message : "Couldn't send it.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title={`Send ${title}`} onClose={onClose} footer={<button className="ghost-btn" onClick={onClose}>Done</button>}>
      <ErrorNote message={error} />
      <div className="fields">
        <label className="field full">
          Email
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="customer@example.com" list="share-emails" />
          <datalist id="share-emails">
            {people.filter((p) => p.email).map((p) => (
              <option key={p.email} value={p.email}>
                {p.name}
              </option>
            ))}
          </datalist>
        </label>
        <div className="full" style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <button className="primary-btn" disabled={busy || !email.includes("@")} onClick={() => run("email")}>
            Email the link
          </button>
        </div>
        <label className="field full">
          WhatsApp number
          <input value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="94460 44556" list="share-phones" />
          <datalist id="share-phones">
            {people.filter((p) => p.phone).map((p) => (
              <option key={p.phone} value={p.phone}>
                {p.name}
              </option>
            ))}
          </datalist>
        </label>
        <div className="full" style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <button className="ghost-btn" disabled={busy || !internationalDigits(phone)} onClick={() => run("whatsapp")}>
            Open in WhatsApp
          </button>
          <button className="ghost-btn" disabled={busy} onClick={() => run("copy")}>
            {copied ? "Link copied" : "Copy link"}
          </button>
        </div>
        {result && (
          <p className="card-note full">
            {result.emailed_to ? `Emailed to ${result.emailed_to}. ` : ""}The link works until {dayDate(result.expires)} —{" "}
            <a href={result.url} target="_blank" rel="noreferrer">
              open it
            </a>{" "}
            to see what the customer sees.
          </p>
        )}
        <p className="card-note full">The customer can view and print this document only. Links expire after 30 days.</p>
      </div>
    </Modal>
  );
}
