import { useEffect, useState } from "react";
import { ApiError, fetchRotation, saveRotation, type Rotation } from "../api/client";
import { StaleLimitsEditor } from "../crm/StaleLimitsEditor";
import { ErrorNote } from "../crm/ui";
import { useAppData } from "../data/AppDataProvider";

/** Company-wide CRM rules. Changing them needs crm.settings.write. */
export function CrmSettings() {
  const { can } = useAppData();
  const canEdit = can("crm.settings.write");

  return (
    <section>
      <div className="page-head">
        <div className="eyebrow">CRM</div>
        <h1 className="page-title">CRM settings</h1>
        <p className="page-sub">Rules that apply to everyone in this company.</p>
      </div>

      <div className="card settings-card">
        <div className="card-head">
          <span className="card-title">Lead rotation</span>
        </div>
        <RotationEditor canEdit={canEdit} />
      </div>

      <div className="card settings-card">
        <div className="card-head">
          <span className="card-title">When is a deal going stale?</span>
        </div>
        <StaleLimitsEditor canEdit={canEdit} />
      </div>
    </section>
  );
}

function RotationEditor({ canEdit }: { canEdit: boolean }) {
  const { assignees } = useAppData();
  const [rotation, setRotation] = useState<Rotation | null>(null);
  const [enabled, setEnabled] = useState(false);
  const [members, setMembers] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  function load(r: Rotation) {
    setRotation(r);
    setEnabled(r.enabled);
    setMembers(r.user_ids);
  }

  useEffect(() => {
    fetchRotation()
      .then(load)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Couldn't load the rotation."));
  }, []);

  const name = (id: string) => assignees.find((a) => a.id === id)?.display_name ?? "Unknown user";
  const outside = assignees.filter((a) => !members.includes(a.id));
  const changed = rotation && (enabled !== rotation.enabled || members.join() !== rotation.user_ids.join());

  function move(index: number, by: number) {
    const next = [...members];
    [next[index], next[index + by]] = [next[index + by]!, next[index]!];
    setMembers(next);
  }

  async function save() {
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      const saved = await saveRotation({ enabled: enabled && members.length > 0, user_ids: members });
      load(saved);
      setNotice(saved.enabled ? `Saved. ${saved.next_user_name} gets the next lead.` : "Saved. The rotation is off.");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't save.");
    } finally {
      setSaving(false);
    }
  }

  if (!rotation) return <ErrorNote message={error} />;

  return (
    <div className="settings-block">
      <p className="card-note" style={{ marginTop: 0 }}>
        New leads go to these people in turn: web enquiries, CSV rows with no Owner, and leads created with “Next in
        rotation”. Anyone deactivated is skipped.
      </p>
      <label className="toggle-row">
        <input type="checkbox" checked={enabled} disabled={!canEdit} onChange={(e) => setEnabled(e.target.checked)} />
        <span>Hand out new leads in rotation</span>
      </label>

      <ol className="rotation-list">
        {members.map((id, i) => (
          <li key={id}>
            <span className="rotation-pos">{i + 1}</span>
            <span className="grow">
              {name(id)}
              {rotation.enabled && rotation.next_user_id === id && !changed && <span className="badge accent">Next up</span>}
            </span>
            {canEdit && (
              <span className="rotation-actions">
                <button className="ghost-btn sm" disabled={i === 0} onClick={() => move(i, -1)} aria-label={`Move ${name(id)} up`}>
                  ↑
                </button>
                <button
                  className="ghost-btn sm"
                  disabled={i === members.length - 1}
                  onClick={() => move(i, 1)}
                  aria-label={`Move ${name(id)} down`}
                >
                  ↓
                </button>
                <button className="ghost-btn sm" onClick={() => setMembers(members.filter((m) => m !== id))}>
                  Remove
                </button>
              </span>
            )}
          </li>
        ))}
        {members.length === 0 && <li className="card-note">Nobody in the rotation yet.</li>}
      </ol>

      {canEdit && outside.length > 0 && (
        <label className="field" style={{ maxWidth: 320 }}>
          <span>Add someone</span>
          <select value="" onChange={(e) => e.target.value && setMembers([...members, e.target.value])} aria-label="Add to rotation">
            <option value="">Choose a person…</option>
            {outside.map((a) => (
              <option key={a.id} value={a.id}>
                {a.display_name}
              </option>
            ))}
          </select>
        </label>
      )}

      <ErrorNote message={error} />
      {notice && <div className="notice good">{notice}</div>}
      {canEdit && (
        <div className="form-actions">
          <button className="primary-btn" disabled={!changed || saving} onClick={save}>
            {saving ? "Saving…" : "Save rotation"}
          </button>
        </div>
      )}
      {!canEdit && <p className="card-note">Changing the rotation needs the crm.settings.write permission.</p>}
    </div>
  );
}
