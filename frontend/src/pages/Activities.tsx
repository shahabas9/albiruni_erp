import { useEffect, useState } from "react";
import {
  ACTIVITY_TYPES,
  ApiError,
  createActivity,
  fetchActivities,
  fetchCustomers,
  fetchLeads,
  fetchOpportunities,
  updateActivity,
  type Activity,
  type ActivityType,
  type Customer,
  type Lead,
  type Opportunity,
} from "../api/client";

type RelatedKind = "lead" | "customer" | "opportunity";

export function Activities() {
  const [activities, setActivities] = useState<Activity[]>([]);
  const [leads, setLeads] = useState<Lead[]>([]);
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [opportunities, setOpportunities] = useState<Opportunity[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);

  async function refresh() {
    setLoading(true);
    try {
      const [a, l, c, o] = await Promise.all([
        fetchActivities(),
        fetchLeads(),
        fetchCustomers(),
        fetchOpportunities(),
      ]);
      setActivities(a);
      setLeads(l);
      setCustomers(c);
      setOpportunities(o);
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

  const hasTargets = leads.length > 0 || customers.length > 0 || opportunities.length > 0;

  async function toggleDone(a: Activity) {
    await updateActivity(a.id, { done: !a.done });
    refresh();
  }

  return (
    <section>
      <div className="page-head">
        <div className="eyebrow">CRM</div>
        <h1 className="page-title">Activities</h1>
        <p className="page-sub">The relationship timeline — calls, meetings, tasks and notes logged against a lead, customer or opportunity.</p>
      </div>

      {error && <div className="error-banner">{error}</div>}

      <div className="toolbar">
        <div />
        <button className="primary-btn" disabled={!hasTargets} onClick={() => setShowForm((v) => !v)}>
          {showForm ? "Cancel" : "+ Log activity"}
        </button>
      </div>
      {!hasTargets && !loading && (
        <p className="footnote">Add a lead, customer or opportunity first — every activity is logged against one.</p>
      )}

      {showForm && (
        <ActivityForm
          leads={leads}
          customers={customers}
          opportunities={opportunities}
          onDone={() => {
            setShowForm(false);
            refresh();
          }}
        />
      )}

      {!loading && activities.length === 0 && !showForm && (
        <div className="card" style={{ textAlign: "center", color: "var(--ink-dim)" }}>
          No activities logged yet.
        </div>
      )}

      {activities.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Done</th>
                <th>Type</th>
                <th>Subject</th>
                <th>Related to</th>
                <th>Due</th>
              </tr>
            </thead>
            <tbody>
              {activities.map((a) => (
                <tr key={a.id} style={a.done ? { opacity: 0.55 } : undefined}>
                  <td>
                    <input type="checkbox" checked={a.done} onChange={() => toggleDone(a)} />
                  </td>
                  <td>
                    <span className="badge l2">{a.type}</span>
                  </td>
                  <td style={a.done ? { textDecoration: "line-through" } : undefined}>{a.subject}</td>
                  <td>{a.related_label}</td>
                  <td>{a.due_date ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function ActivityForm({
  leads,
  customers,
  opportunities,
  onDone,
}: {
  leads: Lead[];
  customers: Customer[];
  opportunities: Opportunity[];
  onDone: () => void;
}) {
  const firstKind: RelatedKind = leads.length > 0 ? "lead" : customers.length > 0 ? "customer" : "opportunity";
  const [type, setType] = useState<ActivityType>("Call");
  const [subject, setSubject] = useState("");
  const [dueDate, setDueDate] = useState("");
  const [notes, setNotes] = useState("");
  const [relatedKind, setRelatedKind] = useState<RelatedKind>(firstKind);
  const [relatedId, setRelatedId] = useState(
    firstKind === "lead" ? leads[0]?.id : firstKind === "customer" ? customers[0]?.id : opportunities[0]?.id,
  );
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const optionsFor: Record<RelatedKind, { id: string; label: string }[]> = {
    lead: leads.map((l) => ({ id: l.id, label: l.name })),
    customer: customers.map((c) => ({ id: c.id, label: c.name })),
    opportunity: opportunities.map((o) => ({ id: o.id, label: o.name })),
  };

  function changeKind(kind: RelatedKind) {
    setRelatedKind(kind);
    setRelatedId(optionsFor[kind][0]?.id);
  }

  async function save() {
    if (!relatedId) return;
    setSaving(true);
    setError(null);
    try {
      await createActivity({
        type,
        subject,
        notes,
        due_date: dueDate || null,
        lead_id: relatedKind === "lead" ? relatedId : null,
        customer_id: relatedKind === "customer" ? relatedId : null,
        opportunity_id: relatedKind === "opportunity" ? relatedId : null,
      });
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
          <span>Type</span>
          <select value={type} onChange={(e) => setType(e.target.value as ActivityType)}>
            {ACTIVITY_TYPES.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>Subject</span>
          <input value={subject} onChange={(e) => setSubject(e.target.value)} autoFocus />
        </label>
        <label className="field">
          <span>Due date</span>
          <input type="date" value={dueDate} onChange={(e) => setDueDate(e.target.value)} />
        </label>
        <label className="field">
          <span>Related to</span>
          <select value={relatedKind} onChange={(e) => changeKind(e.target.value as RelatedKind)}>
            {leads.length > 0 && <option value="lead">Lead</option>}
            {customers.length > 0 && <option value="customer">Customer</option>}
            {opportunities.length > 0 && <option value="opportunity">Opportunity</option>}
          </select>
        </label>
        <label className="field">
          <span>{relatedKind === "lead" ? "Lead" : relatedKind === "customer" ? "Customer" : "Opportunity"}</span>
          <select value={relatedId} onChange={(e) => setRelatedId(e.target.value)}>
            {optionsFor[relatedKind].map((opt) => (
              <option key={opt.id} value={opt.id}>
                {opt.label}
              </option>
            ))}
          </select>
        </label>
      </div>
      <label className="field">
        <span>Notes</span>
        <input value={notes} onChange={(e) => setNotes(e.target.value)} />
      </label>
      {error && <div className="error-banner">{error}</div>}
      <div className="form-actions">
        <button className="primary-btn" disabled={!subject.trim() || !relatedId || saving} onClick={save}>
          {saving ? "Saving…" : "Save"}
        </button>
        <button className="secondary-btn" onClick={onDone}>
          Cancel
        </button>
      </div>
    </div>
  );
}
