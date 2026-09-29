import { useCallback, useEffect, useState } from "react";
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
} from "../api/client";
import { Icon } from "../components/Icon";
import { useOpenOpportunity } from "../crm/drawerHost";
import { Pager, SearchBox } from "../crm/ui";
import { PAGE_SIZE, usePaged } from "../lib/usePaged";
import { useAppData } from "../data/AppDataProvider";
import { relativeDue } from "../lib/format";

type RelatedKind = "lead" | "customer" | "opportunity";
type Show = "open" | "overdue" | "done" | "all";

function endOfLocalDay(isoDate: string): string {
  const [y, m, d] = isoDate.split("-").map(Number);
  return new Date(y!, m! - 1, d!, 23, 59, 59).toISOString();
}

export function Activities() {
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [params, setParams] = useSearchParams();
  const show = (params.get("show") as Show) || "open";
  const setShow = (next: Show) => setParams(next === "open" ? {} : { show: next }, { replace: true });
  const [mine, setMine] = useState(false);
  // Overdue status and ordering (overdue first, then soonest due) come from the API.
  const { crm, version, refresh: refreshShared, can } = useAppData();
  const openOpp = useOpenOpportunity();
  const list = usePaged(
    (limit, offset) => fetchActivities({ show, owner: mine ? "me" : "", limit, offset }),
    `${show}|${mine}`,
    version,
  );
  const visible = list.rows;
  const counts: Partial<Record<Show, number>> = { open: crm?.open_followups, overdue: crm?.overdue_followups };

  async function toggleDone(a: Activity) {
    try {
      await updateActivity(a.id, { done: !a.done });
      await refreshShared();
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

      {(error ?? list.error) && <div className="error-banner">{error ?? list.error}</div>}

      <div className="toolbar">
        <div className="filters">
          {(["open", "overdue", "done", "all"] as const).map((f) => (
            <button
              key={f}
              className={show === f ? "on" : ""}
              onClick={() => setShow(f)}
              style={f === "overdue" && (counts.overdue ?? 0) > 0 && show !== f ? { color: "var(--bad)", borderColor: "var(--bad)" } : undefined}
            >
              {f === "open" ? "Open" : f === "overdue" ? "Overdue" : f === "done" ? "Done" : "All"}
              {counts[f] !== undefined && ` (${counts[f]})`}
            </button>
          ))}
        </div>
        <div className="filters" aria-label="Owner filter">
          <button className={!mine ? "on" : ""} onClick={() => setMine(false)}>
            Everyone
          </button>
          <button className={mine ? "on" : ""} onClick={() => setMine(true)}>
            Mine
          </button>
        </div>
        {can("crm.activity.write") && (
          <button className="primary-btn" onClick={() => setShowForm((v) => !v)}>
            {showForm ? "Cancel" : "+ Log activity"}
          </button>
        )}
      </div>

      {showForm && (
        <ActivityForm
          onDone={(saved) => {
            setShowForm(false);
            if (saved) void refreshShared();
          }}
        />
      )}

      {!list.loading && list.total === 0 && !showForm && (
        <div className="card" style={{ textAlign: "center", color: "var(--ink-dim)" }}>
          {show === "overdue" ? "Nothing overdue. You're clear." : show === "all" && !mine ? "No activities logged yet." : "Nothing here."}
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
                <tr key={a.id} className={a.is_overdue ? "activity-row overdue" : undefined} style={a.done ? { opacity: 0.55 } : undefined}>
                  <td>
                    <input
                      type="checkbox"
                      checked={a.done}
                      disabled={!can("crm.activity.write")}
                      aria-label={a.done ? "Mark as not done" : "Mark as done"}
                      onChange={() => toggleDone(a)}
                    />
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
                    {a.due_at ? (
                      <>
                        {!a.done && (
                          <span className={`followup${a.is_overdue ? " overdue" : ""}`}>
                            <Icon name={a.is_overdue ? "alert" : "clock"} size={14} /> {relativeDue(a.due_at)}
                          </span>
                        )}
                        <span className="sub">{a.due_date}</span>
                      </>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td>{a.owner_name ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <Pager page={list.page} pageSize={PAGE_SIZE} total={list.total} onPage={list.setPage} />
    </section>
  );
}

const PICK_LIMIT = 20;

/** Records an activity can be logged against, searched on the server. */
function useRelatedOptions(kind: RelatedKind, q: string) {
  const { can } = useAppData();
  const [options, setOptions] = useState<{ id: string; label: string }[]>([]);
  useEffect(() => {
    let current = true;
    const load = async () => {
      if (kind === "lead" && can("crm.lead.read")) {
        const page = await fetchLeads({ q, status: "open", limit: PICK_LIMIT });
        return page.rows.map((l) => ({ id: l.id, label: l.company_name ? `${l.company_name} (${l.name})` : l.name }));
      }
      if (kind === "opportunity" && can("crm.opportunity.read")) {
        const page = await fetchOpportunities({ q, stage: "open", limit: PICK_LIMIT });
        return page.rows.map((o) => ({ id: o.id, label: `${o.name} — ${o.customer_name}` }));
      }
      if (kind === "customer" && can("sales.customer.read")) {
        const page = await fetchCustomers({ q, active: true, limit: PICK_LIMIT });
        return page.rows.map((c) => ({ id: c.id, label: c.name }));
      }
      return [];
    };
    load()
      .then((rows) => current && setOptions(rows))
      .catch(() => current && setOptions([]));
    return () => {
      current = false;
    };
  }, [kind, q, can]);
  return options;
}

function ActivityForm({ onDone }: { onDone: (saved: boolean) => void }) {
  const { can } = useAppData();
  const kinds = (
    [
      ["lead", "crm.lead.read"],
      ["opportunity", "crm.opportunity.read"],
      ["customer", "sales.customer.read"],
    ] as const
  ).filter(([, p]) => can(p)).map(([k]) => k as RelatedKind);
  const [type, setType] = useState<ActivityType>("Call");
  const [subject, setSubject] = useState("");
  const [dueDate, setDueDate] = useState("");
  const [notes, setNotes] = useState("");
  const [relatedKind, setRelatedKind] = useState<RelatedKind>(kinds[0] ?? "lead");
  const [search, setSearch] = useState("");
  const onSearch = useCallback((q: string) => setSearch(q), []);
  const options = useRelatedOptions(relatedKind, search);
  const [picked, setPicked] = useState<string | undefined>();
  const relatedId = picked && options.some((o) => o.id === picked) ? picked : options[0]?.id;
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  function changeKind(kind: RelatedKind) {
    setRelatedKind(kind);
    setPicked(undefined);
    setSearch("");
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
        // Due by the end of that day in *your* timezone (the API's date-only default is end of day UTC).
        due_at: dueDate ? endOfLocalDay(dueDate) : null,
        lead_id: relatedKind === "lead" ? relatedId : null,
        customer_id: relatedKind === "customer" ? relatedId : null,
        opportunity_id: relatedKind === "opportunity" ? relatedId : null,
      });
      onDone(true);
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
            {kinds.includes("lead") && <option value="lead">Open lead</option>}
            {kinds.includes("opportunity") && <option value="opportunity">Open opportunity</option>}
            {kinds.includes("customer") && <option value="customer">Customer</option>}
          </select>
        </label>
        <div className="field">
          <span>{relatedKind === "lead" ? "Lead" : relatedKind === "customer" ? "Customer" : "Opportunity"}</span>
          <SearchBox key={relatedKind} value={search} onChange={onSearch} placeholder="Type to search…" />
          <select value={relatedId ?? ""} onChange={(e) => setPicked(e.target.value)} aria-label="Pick the record">
            {options.length === 0 && <option value="">{search ? "No match" : "Nothing to pick"}</option>}
            {options.map((opt) => (
              <option key={opt.id} value={opt.id}>
                {opt.label}
              </option>
            ))}
          </select>
        </div>
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
        <button className="secondary-btn" onClick={() => onDone(false)}>
          Cancel
        </button>
      </div>
    </div>
  );
}
