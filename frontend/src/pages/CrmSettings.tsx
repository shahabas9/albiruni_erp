import { useEffect, useState } from "react";
import {
  ApiError,
  createCustomField,
  fetchCustomFields,
  fetchRotation,
  fetchWebForm,
  newWebFormKey,
  saveRotation,
  saveWebForm,
  webFormUrl,
  updateCustomField,
  type CustomField,
  type CustomFieldType,
  type RecordType,
  type Rotation,
  type WebForm,
} from "../api/client";
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
          <span className="card-title">Web enquiry form</span>
        </div>
        {canEdit ? <WebFormEditor /> : <p className="card-note">Setting up the web form needs the crm.settings.write permission.</p>}
      </div>

      <div className="card settings-card">
        <div className="card-head">
          <span className="card-title">Custom fields</span>
        </div>
        <CustomFieldsEditor canEdit={canEdit} />
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

const RECORD_LABELS: Record<RecordType, string> = { lead: "Leads", opportunity: "Deals", customer: "Customers" };
const TYPE_LABELS: Record<CustomFieldType, string> = {
  text: "Text",
  number: "Number",
  date: "Date",
  select: "Dropdown",
  checkbox: "Yes / no",
};

function splitChoices(text: string): string[] {
  return text
    .split(/[\n,]/)
    .map((c) => c.trim())
    .filter(Boolean);
}

/** Extra fields on leads, deals and customers. Type can't change once created (saved values depend on it). */
function CustomFieldsEditor({ canEdit }: { canEdit: boolean }) {
  const [recordType, setRecordType] = useState<RecordType>("lead");
  const [fields, setFields] = useState<CustomField[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [label, setLabel] = useState("");
  const [fieldType, setFieldType] = useState<CustomFieldType>("text");
  const [choices, setChoices] = useState("");
  const [editing, setEditing] = useState<string | null>(null);
  const [draftLabel, setDraftLabel] = useState("");
  const [draftChoices, setDraftChoices] = useState("");
  const [busy, setBusy] = useState(false);

  async function load(type = recordType) {
    try {
      setFields(await fetchCustomFields(type, true));
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't load the fields.");
    }
  }

  useEffect(() => {
    setFields(null);
    setEditing(null);
    void load(recordType);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [recordType]);

  async function act(action: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await action();
      await load();
      return true;
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't save.");
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function add() {
    const ok = await act(() =>
      createCustomField({
        record_type: recordType,
        label: label.trim(),
        field_type: fieldType,
        options: fieldType === "select" ? splitChoices(choices) : [],
      }),
    );
    if (ok) {
      setLabel("");
      setChoices("");
      setFieldType("text");
    }
  }

  const active = (fields ?? []).filter((f) => f.active);
  const archived = (fields ?? []).filter((f) => !f.active);

  function move(index: number, by: number) {
    const a = active[index]!;
    const b = active[index + by]!;
    void act(async () => {
      await updateCustomField(a.id, { position: b.position });
      await updateCustomField(b.id, { position: a.position });
    });
  }

  return (
    <div className="settings-block">
      <div className="filters" role="tablist" aria-label="Record type">
        {(Object.keys(RECORD_LABELS) as RecordType[]).map((t) => (
          <button key={t} role="tab" aria-selected={recordType === t} className={recordType === t ? "on" : ""} onClick={() => setRecordType(t)}>
            {RECORD_LABELS[t]}
          </button>
        ))}
      </div>

      <ol className="rotation-list">
        {fields === null && <li className="card-note">Loading…</li>}
        {fields !== null && active.length === 0 && (
          <li className="card-note">No custom fields on {RECORD_LABELS[recordType].toLowerCase()} yet.</li>
        )}
        {active.map((f, i) =>
          editing === f.id ? (
            <li key={f.id} className="field-edit">
              <label className="field">
                <span>Name</span>
                <input value={draftLabel} onChange={(e) => setDraftLabel(e.target.value)} />
              </label>
              {f.field_type === "select" && (
                <label className="field">
                  <span>Choices (one per line)</span>
                  <textarea rows={4} value={draftChoices} onChange={(e) => setDraftChoices(e.target.value)} />
                </label>
              )}
              <div className="form-actions">
                <button
                  className="primary-btn"
                  disabled={busy || !draftLabel.trim()}
                  onClick={async () => {
                    const ok = await act(() =>
                      updateCustomField(f.id, {
                        label: draftLabel.trim(),
                        ...(f.field_type === "select" ? { options: splitChoices(draftChoices) } : {}),
                      }),
                    );
                    if (ok) setEditing(null);
                  }}
                >
                  Save
                </button>
                <button className="secondary-btn" onClick={() => setEditing(null)}>
                  Cancel
                </button>
              </div>
            </li>
          ) : (
            <li key={f.id}>
              <span className="grow">
                <b>{f.label}</b>
                <span className="badge muted">{TYPE_LABELS[f.field_type]}</span>
                {f.field_type === "select" && <small className="card-note">{f.options.join(", ")}</small>}
              </span>
              {canEdit && (
                <span className="rotation-actions">
                  <button className="ghost-btn sm" disabled={busy || i === 0} onClick={() => move(i, -1)} aria-label={`Move ${f.label} up`}>
                    ↑
                  </button>
                  <button
                    className="ghost-btn sm"
                    disabled={busy || i === active.length - 1}
                    onClick={() => move(i, 1)}
                    aria-label={`Move ${f.label} down`}
                  >
                    ↓
                  </button>
                  <button
                    className="ghost-btn sm"
                    onClick={() => {
                      setEditing(f.id);
                      setDraftLabel(f.label);
                      setDraftChoices(f.options.join("\n"));
                    }}
                  >
                    Edit
                  </button>
                  <button className="ghost-btn sm" disabled={busy} onClick={() => act(() => updateCustomField(f.id, { active: false }))}>
                    Archive
                  </button>
                </span>
              )}
            </li>
          ),
        )}
      </ol>

      {archived.length > 0 && (
        <details className="archived-fields">
          <summary>
            {archived.length} archived field{archived.length === 1 ? "" : "s"} — hidden from forms, saved values kept
          </summary>
          <ul>
            {archived.map((f) => (
              <li key={f.id}>
                {f.label} <span className="badge muted">{TYPE_LABELS[f.field_type]}</span>
                {canEdit && (
                  <button className="link-btn" disabled={busy} onClick={() => act(() => updateCustomField(f.id, { active: true }))}>
                    Restore
                  </button>
                )}
              </li>
            ))}
          </ul>
        </details>
      )}

      {canEdit && (
        <div className="field-grid add-field">
          <label className="field">
            <span>New field on {RECORD_LABELS[recordType].toLowerCase()}</span>
            <input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="e.g. Budget, City, Site visit" maxLength={80} />
          </label>
          <label className="field">
            <span>Type</span>
            <select value={fieldType} onChange={(e) => setFieldType(e.target.value as CustomFieldType)}>
              {(Object.keys(TYPE_LABELS) as CustomFieldType[]).map((t) => (
                <option key={t} value={t}>
                  {TYPE_LABELS[t]}
                </option>
              ))}
            </select>
          </label>
          {fieldType === "select" && (
            <label className="field full">
              <span>Choices (one per line)</span>
              <textarea rows={3} value={choices} onChange={(e) => setChoices(e.target.value)} placeholder={"Kozhikode\nKannur\nMalappuram"} />
            </label>
          )}
          <div className="field full">
            <button
              className="primary-btn"
              style={{ justifySelf: "start" }}
              disabled={busy || !label.trim() || (fieldType === "select" && splitChoices(choices).length === 0)}
              onClick={add}
            >
              Add field
            </button>
          </div>
        </div>
      )}
      <ErrorNote message={error} />
      {!canEdit && <p className="card-note">Changing fields needs the crm.settings.write permission.</p>}
    </div>
  );
}

function CopyField({ label, value, multiline = false }: { label: string; value: string; multiline?: boolean }) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
    }
  }
  return (
    <div className="field full">
      <span>{label}</span>
      <div className="copy-field">
        {multiline ? <textarea readOnly rows={3} value={value} /> : <input readOnly value={value} />}
        <button type="button" className="ghost-btn sm" onClick={copy}>
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
    </div>
  );
}

/** Public form on the company's website; each enquiry becomes a lead (or a note on an existing one). */
function WebFormEditor() {
  const [form, setForm] = useState<WebForm | null>(null);
  const [source, setSource] = useState("");
  const [thankYou, setThankYou] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  function load(f: WebForm) {
    setForm(f);
    setSource(f.source);
    setThankYou(f.thank_you);
  }

  useEffect(() => {
    fetchWebForm()
      .then(load)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Couldn't load the web form."));
  }, []);

  async function act(action: () => Promise<WebForm>, ok: string) {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      load(await action());
      setNotice(ok);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't save.");
    } finally {
      setBusy(false);
    }
  }

  if (!form) return <ErrorNote message={error} />;
  const url = form.key ? webFormUrl(form.key) : "";
  const embed = `<iframe src="${url}" title="Enquiry form" style="width:100%;max-width:560px;height:680px;border:0"></iframe>`;
  const changed = source !== form.source || thankYou !== form.thank_you;

  return (
    <div className="settings-block">
      <p className="card-note" style={{ marginTop: 0 }}>
        A contact form for your website. Each enquiry becomes a new lead (given out by the lead rotation when it's on), or a
        note on the lead if the phone or email is already known. Bots are filtered with a hidden field and a rate limit.
      </p>
      <label className="toggle-row">
        <input
          type="checkbox"
          checked={form.enabled}
          disabled={busy}
          onChange={(e) =>
            act(() => saveWebForm({ enabled: e.target.checked }), e.target.checked ? "The form is live." : "The form is off.")
          }
        />
        <span>Accept enquiries from the web form</span>
      </label>

      {form.enabled && form.key && (
        <div className="field-grid" style={{ marginTop: 12 }}>
          <CopyField label="Link to share" value={url} />
          <CopyField label="Embed on your website" value={embed} multiline />
          <p className="card-note field full" style={{ margin: 0 }}>
            <a href={url} target="_blank" rel="noreferrer">
              Open the form
            </a>{" "}
            · Developers can also <code>POST</code> JSON (<code>name</code>, <code>company</code>, <code>phone</code>,{" "}
            <code>email</code>, <code>message</code>) to the same link.
          </p>
        </div>
      )}

      <div className="field-grid" style={{ marginTop: 12 }}>
        <label className="field">
          <span>Lead source</span>
          <input value={source} maxLength={60} onChange={(e) => setSource(e.target.value)} />
        </label>
        <label className="field full">
          <span>Thank-you message</span>
          <textarea rows={2} maxLength={300} value={thankYou} onChange={(e) => setThankYou(e.target.value)} />
        </label>
      </div>

      <ErrorNote message={error} />
      {notice && <div className="notice good">{notice}</div>}
      <div className="form-actions">
        <button
          className="primary-btn"
          disabled={busy || !changed || !source.trim() || !thankYou.trim()}
          onClick={() => act(() => saveWebForm({ source: source.trim(), thank_you: thankYou.trim() }), "Saved.")}
        >
          Save
        </button>
        {form.key && (
          <button
            className="ghost-btn"
            disabled={busy}
            onClick={() => {
              if (window.confirm("Make a new link? The current link and embed stop working immediately.")) {
                void act(newWebFormKey, "New link created — update it on your website.");
              }
            }}
          >
            New link
          </button>
        )}
      </div>
    </div>
  );
}
