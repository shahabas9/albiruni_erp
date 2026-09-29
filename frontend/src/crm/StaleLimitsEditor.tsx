import { useEffect, useState } from "react";
import { ApiError, fetchStaleLimits, saveStaleLimits, type StaleLimits } from "../api/client";
import { ErrorNote } from "./ui";

const STAGES: (keyof StaleLimits)[] = ["New", "Qualified", "Proposal", "Negotiation"];

const LIMIT_HINTS: Record<keyof StaleLimits, string> = {
  New: "A fresh deal nobody has called",
  Qualified: "Qualified, but no proposal yet",
  Proposal: "Quote sent, waiting on the customer",
  Negotiation: "Closing — goes cold fastest",
};

/** Per-company "going stale" limits: days a deal may sit untouched in each stage. */
export function StaleLimitsEditor({
  canEdit,
  onSaved,
  onCancel,
}: {
  canEdit: boolean;
  onSaved?: () => void;
  onCancel?: () => void;
}) {
  const [limits, setLimits] = useState<StaleLimits | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    fetchStaleLimits()
      .then(setLimits)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Couldn't load the limits."));
  }, []);

  async function save() {
    if (!limits) return;
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      setLimits(await saveStaleLimits(limits));
      setSaved(true);
      onSaved?.();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't save.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="settings-block">
      <p className="card-note" style={{ marginTop: 0 }}>
        A deal is flagged when nothing — a call, a follow-up, a quotation or a stage change — has touched it for this many days.
        Use 0 to never flag a stage.{!canEdit && " Changing these needs the crm.settings.write permission."}
      </p>
      {limits && (
        <div className="limits-grid">
          {STAGES.map((key) => (
            <label className="field" key={key}>
              <span>{key}</span>
              <div className="input-suffix">
                <input
                  type="number"
                  min={0}
                  max={365}
                  value={limits[key]}
                  disabled={!canEdit}
                  onChange={(e) => {
                    setSaved(false);
                    setLimits({ ...limits, [key]: Math.max(0, Math.min(365, Number(e.target.value) || 0)) });
                  }}
                />
                <span>{limits[key] === 0 ? "off" : "days"}</span>
              </div>
              <small>{LIMIT_HINTS[key]}</small>
            </label>
          ))}
        </div>
      )}
      <ErrorNote message={error} />
      {saved && !onSaved && <div className="notice good">Saved for the company.</div>}
      <div className="form-actions">
        {onCancel && (
          <button type="button" className="ghost-btn" onClick={onCancel}>
            {canEdit ? "Cancel" : "Close"}
          </button>
        )}
        {canEdit && (
          <button className="primary-btn" disabled={!limits || saving} onClick={save}>
            {saving ? "Saving…" : "Save for the company"}
          </button>
        )}
      </div>
    </div>
  );
}
