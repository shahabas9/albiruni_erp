import { useEffect, useState } from "react";
import {
  ApiError,
  LEAD_STATUSES,
  convertLead,
  createLead,
  fetchLeads,
  updateLead,
  type Lead,
  type LeadStatus,
} from "../api/client";

function statusClass(status: LeadStatus) {
  if (status === "Converted") return "status-confirmed";
  if (status === "Lost") return "status-draft";
  if (status === "Qualified") return "status-pending";
  return "status-draft";
}

export function Leads() {
  const [leads, setLeads] = useState<Lead[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [convertingId, setConvertingId] = useState<string | null>(null);

  async function refresh() {
    setLoading(true);
    try {
      setLeads(await fetchLeads());
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't reach the Albiruni API.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  return (
    <section>
      <div className="page-head">
        <div className="eyebrow">CRM</div>
        <h1 className="page-title">Leads</h1>
        <p className="page-sub">Raw, unqualified interest. Convert a qualified lead into a real Customer, Contact and Opportunity in one step.</p>
      </div>

      {error && <div className="error-banner">{error}</div>}

      <div className="toolbar">
        <div />
        <button className="primary-btn" onClick={() => setShowForm((v) => !v)}>
          {showForm ? "Cancel" : "+ New lead"}
        </button>
      </div>

      {showForm && <LeadForm onDone={() => { setShowForm(false); refresh(); }} />}

      {!loading && leads.length === 0 && !showForm && (
        <div className="card" style={{ textAlign: "center", color: "var(--ink-dim)" }}>
          No leads yet — add one above.
        </div>
      )}

      {leads.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Company</th>
                <th>Source</th>
                <th>Status</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {leads.map((l) =>
                editingId === l.id ? (
                  <tr key={l.id}>
                    <td colSpan={5}>
                      <LeadForm lead={l} onDone={() => { setEditingId(null); refresh(); }} />
                    </td>
                  </tr>
                ) : convertingId === l.id ? (
                  <tr key={l.id}>
                    <td colSpan={5}>
                      <ConvertForm
                        lead={l}
                        onDone={() => {
                          setConvertingId(null);
                          refresh();
                        }}
                        onCancel={() => setConvertingId(null)}
                      />
                    </td>
                  </tr>
                ) : (
                  <tr key={l.id}>
                    <td>{l.name}</td>
                    <td>{l.company_name || "—"}</td>
                    <td>{l.source || "—"}</td>
                    <td>
                      <span className={`badge ${statusClass(l.status)}`}>{l.status}</span>
                    </td>
                    <td style={{ display: "flex", gap: 8 }}>
                      {l.status !== "Converted" && (
                        <>
                          <button className="secondary-btn" onClick={() => setEditingId(l.id)}>
                            Edit
                          </button>
                          <button className="primary-btn" onClick={() => setConvertingId(l.id)}>
                            Convert
                          </button>
                        </>
                      )}
                    </td>
                  </tr>
                ),
              )}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function LeadForm({ lead, onDone }: { lead?: Lead; onDone: () => void }) {
  const [name, setName] = useState(lead?.name ?? "");
  const [companyName, setCompanyName] = useState(lead?.company_name ?? "");
  const [email, setEmail] = useState(lead?.email ?? "");
  const [phone, setPhone] = useState(lead?.phone ?? "");
  const [source, setSource] = useState(lead?.source ?? "");
  const [status, setStatus] = useState<LeadStatus>(lead?.status ?? "New");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function save() {
    setSaving(true);
    setError(null);
    try {
      if (lead) {
        await updateLead(lead.id, { name, company_name: companyName, email, phone, source, status });
      } else {
        await createLead({ name, company_name: companyName, email, phone, source });
      }
      onDone();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't save.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="card form-card">
      <div className="field-grid">
        <label className="field">
          <span>Name</span>
          <input value={name} onChange={(e) => setName(e.target.value)} autoFocus />
        </label>
        <label className="field">
          <span>Company</span>
          <input value={companyName} onChange={(e) => setCompanyName(e.target.value)} />
        </label>
        <label className="field">
          <span>Email</span>
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
        </label>
        <label className="field">
          <span>Phone</span>
          <input value={phone} onChange={(e) => setPhone(e.target.value)} />
        </label>
        <label className="field">
          <span>Source</span>
          <input value={source} onChange={(e) => setSource(e.target.value)} placeholder="e.g. Referral, Website" />
        </label>
        {lead && (
          <label className="field">
            <span>Status</span>
            <select value={status} onChange={(e) => setStatus(e.target.value as LeadStatus)}>
              {LEAD_STATUSES.filter((s) => s !== "Converted").map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>
      {error && <div className="error-banner">{error}</div>}
      <div className="form-actions">
        <button className="primary-btn" disabled={!name.trim() || saving} onClick={save}>
          {saving ? "Saving…" : "Save"}
        </button>
        <button className="secondary-btn" onClick={onDone}>
          Cancel
        </button>
      </div>
    </div>
  );
}

function ConvertForm({ lead, onDone, onCancel }: { lead: Lead; onDone: () => void; onCancel: () => void }) {
  const [createOpportunity, setCreateOpportunity] = useState(true);
  const [value, setValue] = useState("0");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function save() {
    setSaving(true);
    setError(null);
    try {
      await convertLead(lead.id, { create_opportunity: createOpportunity, opportunity_value: Number(value) });
      onDone();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't convert.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="card form-card">
      <p style={{ margin: 0, fontSize: 13, color: "var(--ink-dim)" }}>
        Converts <b style={{ color: "var(--ink)" }}>{lead.name}</b> into a Customer (
        <span className="mono">{lead.company_name || lead.name}</span>) and a Contact.
      </p>
      <label className="field" style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
        <input type="checkbox" checked={createOpportunity} onChange={(e) => setCreateOpportunity(e.target.checked)} />
        <span>Also open an Opportunity</span>
      </label>
      {createOpportunity && (
        <label className="field" style={{ maxWidth: 220 }}>
          <span>Estimated value (₹)</span>
          <input type="number" min={0} value={value} onChange={(e) => setValue(e.target.value)} />
        </label>
      )}
      {error && <div className="error-banner">{error}</div>}
      <div className="form-actions">
        <button className="primary-btn" disabled={saving} onClick={save}>
          {saving ? "Converting…" : "Confirm conversion"}
        </button>
        <button className="secondary-btn" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </div>
  );
}
