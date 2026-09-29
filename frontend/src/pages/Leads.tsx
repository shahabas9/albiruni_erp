import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  ApiError,
  LEAD_STATUSES,
  convertLead,
  crm,
  createLead,
  fetchLeads,
  updateLead,
  type Lead,
  type LeadStatus,
} from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import { useOpenOpportunity } from "../crm/drawerHost";
import { FollowUpModal } from "../crm/forms";
import { FollowUpBadge, OwnerPicker } from "../crm/ui";
import { useAppData } from "../data/AppDataProvider";

type OwnerFilter = "all" | "mine" | "unassigned";

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
  const [followUpFor, setFollowUpFor] = useState<Lead | null>(null);
  const [params] = useSearchParams();
  const [owner, setOwner] = useState<OwnerFilter>((params.get("owner") as OwnerFilter) || "all");
  const { user } = useAuth();
  const { leads: pipelineLeads, assignees, refresh: refreshShared, can } = useAppData();
  const openOpp = useOpenOpportunity();
  // Same rows as /api/leads, plus owner name and follow-up counts from the pipeline API.
  const followUps = new Map(pipelineLeads.map((l) => [l.id, l]));

  async function reload() {
    await Promise.all([refresh(), refreshShared()]);
  }

  async function assign(lead: Lead, ownerId: string | null) {
    try {
      await crm.assignLead(lead.id, ownerId);
      await reload();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't reassign.");
    }
  }

  const visible =
    owner === "mine"
      ? leads.filter((l) => l.owner_user_id === user?.id)
      : owner === "unassigned"
        ? leads.filter((l) => !l.owner_user_id && l.status !== "Converted" && l.status !== "Lost")
        : leads;

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
        <p className="page-sub">Raw, unqualified interest. Give every lead an owner and a next step; convert a qualified one into a Customer, Contact and Opportunity in one step.</p>
      </div>

      {error && <div className="error-banner">{error}</div>}

      <div className="toolbar">
        <div className="filters" aria-label="Owner filter">
          {(["all", "mine", "unassigned"] as const).map((f) => (
            <button key={f} className={owner === f ? "on" : ""} onClick={() => setOwner(f)}>
              {f === "all" ? "Everyone" : f === "mine" ? "Mine" : "Unassigned"}
            </button>
          ))}
        </div>
        <button className="primary-btn" onClick={() => setShowForm((v) => !v)}>
          {showForm ? "Cancel" : "+ New lead"}
        </button>
      </div>

      {showForm && <LeadForm onDone={() => { setShowForm(false); reload(); }} />}

      {!loading && leads.length === 0 && !showForm && (
        <div className="card" style={{ textAlign: "center", color: "var(--ink-dim)" }}>
          No leads yet — add one above.
        </div>
      )}

      {leads.length > 0 && visible.length === 0 && (
        <div className="card" style={{ textAlign: "center", color: "var(--ink-dim)" }}>
          No leads match this filter.
        </div>
      )}

      {visible.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Lead</th>
                <th>Status</th>
                <th>Owner</th>
                <th>Next follow-up</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {visible.map((l) =>
                editingId === l.id ? (
                  <tr key={l.id}>
                    <td colSpan={5}>
                      <LeadForm lead={l} onDone={() => { setEditingId(null); reload(); }} />
                    </td>
                  </tr>
                ) : convertingId === l.id ? (
                  <tr key={l.id}>
                    <td colSpan={5}>
                      <ConvertForm
                        lead={l}
                        onDone={async (opportunityId) => {
                          setConvertingId(null);
                          await reload();
                          if (opportunityId) openOpp(opportunityId);
                        }}
                        onCancel={() => setConvertingId(null)}
                      />
                    </td>
                  </tr>
                ) : (
                  <tr key={l.id}>
                    <td>
                      <b>{l.company_name || l.name}</b>
                      <span className="sub">
                        {[l.company_name ? l.name : "", l.source].filter(Boolean).join(" · ") || "—"}
                      </span>
                    </td>
                    <td>
                      <span className={`badge ${statusClass(l.status)}`}>{l.status}</span>
                    </td>
                    <td>
                      <OwnerPicker
                        value={l.owner_user_id}
                        assignees={assignees}
                        canAssign={can("crm.assign") && l.status !== "Converted"}
                        onChange={(id) => assign(l, id)}
                      />
                    </td>
                    <td>
                      {followUps.get(l.id) ? (
                        <FollowUpBadge
                          overdue={followUps.get(l.id)!.overdue_activities}
                          open={followUps.get(l.id)!.open_activities}
                          nextDueAt={followUps.get(l.id)!.next_due_at}
                        />
                      ) : (
                        "—"
                      )}
                    </td>
                    <td style={{ display: "flex", gap: 6, justifyContent: "flex-end" }}>
                      {l.status === "Converted" && followUps.get(l.id)?.converted_opportunity_id && (
                        <button className="ghost-btn sm" onClick={() => openOpp(followUps.get(l.id)!.converted_opportunity_id!)}>
                          Open deal
                        </button>
                      )}
                      {l.status !== "Converted" && (
                        <>
                          <button className="ghost-btn sm" onClick={() => setEditingId(l.id)}>
                            Edit
                          </button>
                          {can("crm.write") && (
                            <button className="ghost-btn sm" onClick={() => setFollowUpFor(l)}>
                              Follow-up
                            </button>
                          )}
                          <button className="primary-btn sm" onClick={() => setConvertingId(l.id)}>
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

      {followUpFor && (
        <FollowUpModal
          target={{ lead_id: followUpFor.id, name: followUpFor.company_name || followUpFor.name }}
          onClose={() => setFollowUpFor(null)}
          onSaved={async () => {
            setFollowUpFor(null);
            await reload();
          }}
        />
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

function ConvertForm({
  lead,
  onDone,
  onCancel,
}: {
  lead: Lead;
  onDone: (opportunityId: string | null) => void;
  onCancel: () => void;
}) {
  const [createOpportunity, setCreateOpportunity] = useState(true);
  const [value, setValue] = useState("0");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function save() {
    setSaving(true);
    setError(null);
    try {
      const result = await convertLead(lead.id, { create_opportunity: createOpportunity, opportunity_value: Number(value) });
      onDone(result.opportunity_id);
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
