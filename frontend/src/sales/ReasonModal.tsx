import { useState } from "react";
import { ErrorNote, Modal } from "../crm/ui";

/** Asks for a short reason before a cancel/reject-type action. */
export function ReasonModal({
  title,
  label,
  action,
  onClose,
  onConfirm,
}: {
  title: string;
  label: string;
  action: string;
  onClose: () => void;
  onConfirm: (reason: string) => Promise<void>;
}) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await onConfirm(reason.trim());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't do that.");
      setBusy(false);
    }
  }
  return (
    <Modal
      title={title}
      onClose={onClose}
      footer={
        <>
          <button className="ghost-btn" onClick={onClose}>
            Back
          </button>
          <button className="danger-btn" type="submit" form="reason-form" disabled={busy || !reason.trim()}>
            {busy ? "Working…" : action}
          </button>
        </>
      }
    >
      <ErrorNote message={error} />
      <form id="reason-form" onSubmit={submit} className="fields">
        <label className="field full">
          {label}
          <input autoFocus maxLength={200} value={reason} onChange={(e) => setReason(e.target.value)} />
        </label>
      </form>
    </Modal>
  );
}
