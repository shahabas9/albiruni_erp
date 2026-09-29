import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
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
import { Icon } from "../components/Icon";
import { useOpenOpportunity } from "../crm/drawerHost";
import { useAppData } from "../data/AppDataProvider";
import { relativeDue } from "../lib/format";

type RelatedKind = "lead" | "customer" | "opportunity";
type Show = "open" | "overdue" | "done" | "all";

/** A dated follow-up is due by the end of that day, local time — "due today" isn't overdue yet. */
function dueEnd(a: Activity): Date | null {
  if (!a.due_date) return null;
  const [y, m, d] = a.due_date.split("-").map(Number);
  return new Date(y!, m! - 1, d!, 23, 59, 59);
}

function isOverdue(a: Activity, now: Date): boolean {
  const end = dueEnd(a);
  return !a.done && end !== null && end < now;
}

export function Activities() {
  const [activities, setActivities] = useState<Activity[]>([]);
  const [leads, setLeads] = useState<Lead[]>([]);
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [opportunities, setOpportunities] = useState<Opportunity[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [params, setParams] = useSearchParams();
  const show = (params.get("show") as Show) || "open";
  const setShow = (next: Show) => setParams(next === "open" ? {} : { show: next }, { replace: true });
  const { activities: pipelineActivities, refresh: refreshShared } = useAppData();
  const owners = new Map(pipelineActivities.map((a) => [a.id, a.owner_name]));
  const openOpp = useOpenOpportunity();
  const [now] = useState(() => new Date());

  const counts = {
    open: activities.filter((a) => !a.done).length,
    overdue: activities.filter((a) => isOverdue(a, now)).length,
    done: activities.filter((a) => a.done).length,
    all: activities.length,
  };
  const visible = activities
    .filter((a) =>
      show === "open" ? !a.done : show === "overdue" ? isOverdue(a, now) : show === "done" ? a.done : true,
    )
    // Overdue first, then soonest due; undated notes last.
    .sort((a, b) => {
      const oa = isOverdue(a, now) ? 0 : 1;
      const ob = isOverdue(b, now) ? 0 : 1;
      if (oa !== ob) return oa - ob;
      return (dueEnd(a)?.getTime() ?? Infinity) - (dueEnd(b)?.getTime() ?? Infinity);
    });

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
    try {
      await updateActivity(a.id, { done: !a.done });
      await Promise.all([refresh(), refreshShared()]);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't update.");
    }
  }

  return (
    <section>
      <div className="page-head">
        <div className="eyebrow">CRM</div>
        <h1 className="page-title">Activities</h1>
        <p className="page-sub">Follow-ups and the relationship timeline — calls, meetings, tasks and notes against a lead, customer or opportunity. Overdue items sort to the top.</p>
      </div>

      {error && <div className="error-banner">{error}</div>}

      <div className="toolbar">
        <div className="filters">
          {(["open", "overdue", "done", "all"] as const).map((f) => (
            <button
              key={f}
              className={show === f ? "on" : ""}
              onClick={() => setShow(f)}
              style={f === "overdue" && counts.overdue > 0 && show !== f ? { color: "var(--bad)", borderColor: "var(--bad)" } : undefined}
            >
              {f === "open" ? "Open" : f === "overdue" ? "Overdue" : f === "done" ? "Done" : "All"} ({counts[f]})
            </button>
          ))}
        </div>
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
            refreshShared();
          }}
        />
      )}

      {!loading && activities.length === 0 && !showForm && (
        <div className="card" style={{ textAlign: "center", color: "var(--ink-dim)" }}>
          No activities logged yet.
        </div>
      )}

      {activities.length > 0 && visible.length === 0 && (
        <div className="card" style={{ textAlign: "center", color: "var(--ink-dim)" }}>
          {show === "overdue" ? "Nothing overdue. You're clear." : "Nothing here."}
        </div>
      )}

      {visible.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Done</th>
                <th>Type</th>
                <th>Subject</th>
                <th>Related to</th>
                <th>Due</th>
                <th>Owner</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((a) => (
                <tr key={a.id} className={isOverdue(a, now) ? "activity-row overdue" : undefined} style={a.done ? { opacity: 0.55 } : undefined}>
                  <td>
                    <input type="checkbox" checked={a.done} onChange={() => toggleDone(a)} />
                  </td>
                  <td>
                    <span className="badge l2">{a.type}</span>
                  </td>
                  <td style={a.done ? { textDecoration: "line-through" } : undefined}>{a.subject}</td>
                  <td>
                    {a.opportunity_id ? (
                      <button className="link-btn" onClick={() => openOpp(a.opportunity_id!)}>
                        {a.related_label}
                      </button>
                    ) : (
                      a.related_label
                    )}
                  </td>
                  <td>
                    {a.due_date ? (
                      <>
                        {!a.done && dueEnd(a) && (
                          <span className={`followup${isOverdue(a, now) ? " overdue" : ""}`}>
                            <Icon name={isOverdue(a, now) ? "alert" : "clock"} size={14} /> {relativeDue(dueEnd(a)!.toISOString(), now)}
                          </span>
                        )}
                        <span className="sub">{a.due_date}</span>
                      </>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td>{owners.get(a.id) ?? "—"}</td>
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
