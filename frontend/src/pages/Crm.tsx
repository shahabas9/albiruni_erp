import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  ApiError,
  crm,
  CRM_LEAD_STATUSES as LEAD_STATUSES,
  type CrmLead as Lead,
  type CrmLeadStatus as LeadStatus,
  type CrmOpportunity as Opportunity,
  type CrmOpportunityStage as OpportunityStage,
} from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import { Icon } from "../components/Icon";
import { ConvertLeadModal, FollowUpModal, NewLeadModal, NewOpportunityModal } from "../crm/forms";
import { OpportunityDrawer } from "../crm/OpportunityDrawer";
import { ErrorNote, FollowUpBadge, OwnerPicker } from "../crm/ui";
import { useAppData } from "../data/AppDataProvider";
import { dateTime, inrShort, relativeDue } from "../lib/format";

type Tab = "pipeline" | "leads" | "followups";
type OwnerFilter = "all" | "mine" | "unassigned";

const BOARD: OpportunityStage[] = ["New", "Qualified", "Proposal", "Negotiation"];

function byOwner<T extends { owner_id: string | null }>(rows: T[], filter: OwnerFilter, me: string | undefined) {
  if (filter === "mine") return rows.filter((r) => r.owner_id === me);
  if (filter === "unassigned") return rows.filter((r) => !r.owner_id);
  return rows;
}

export function Crm() {
  const [params, setParams] = useSearchParams();
  const tab = (params.get("tab") as Tab) || "pipeline";
  const openOppId = params.get("opp");
  const { user } = useAuth();
  const { leads, opportunities, activities, assignees, error: loadError, refresh, can } = useAppData();
  const [owner, setOwner] = useState<OwnerFilter>((params.get("owner") as OwnerFilter) || "all");
  const [modal, setModal] = useState<
    | { kind: "lead" }
    | { kind: "opp" }
    | { kind: "convert"; lead: Lead }
    | { kind: "followup"; lead_id?: string; opportunity_id?: string; name: string }
    | null
  >(null);
  const [error, setError] = useState<string | null>(null);

  const canWrite = can("crm.write");
  const canAssign = can("crm.assign");
  const overdue = activities.filter((a) => a.is_overdue);

  const setTab = (next: Tab) => {
    const p = new URLSearchParams(params);
    p.set("tab", next);
    p.delete("status");
    setParams(p);
  };
  const openOpp = (id: string | null) => {
    const p = new URLSearchParams(params);
    if (id) p.set("opp", id);
    else p.delete("opp");
    setParams(p);
  };

  async function run(action: () => Promise<unknown>) {
    setError(null);
    try {
      await action();
      await refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not reach the Albiruni API.");
    }
  }

  const openOpps = opportunities.filter((o) => BOARD.includes(o.stage));

  return (
    <section>
      <div className="page-head">
        <div>
          <h1 className="page-title">CRM pipeline</h1>
          <p className="page-sub">
            {openOpps.length} open deal{openOpps.length === 1 ? "" : "s"} worth{" "}
            {inrShort(openOpps.reduce((s, o) => s + o.expected_value, 0))}
            {overdue.length > 0 && (
              <>
                {" · "}
                <b style={{ color: "var(--bad)" }}>{overdue.length} follow-up{overdue.length === 1 ? "" : "s"} overdue</b>
              </>
            )}
          </p>
        </div>
        {canWrite && (
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <button className="ghost-btn" onClick={() => setModal({ kind: "lead" })}>
              <Icon name="plus" size={16} /> Lead
            </button>
            <button className="primary-btn" onClick={() => setModal({ kind: "opp" })}>
              <Icon name="plus" size={16} /> Opportunity
            </button>
          </div>
        )}
      </div>

      <div className="tabs" role="tablist">
        {(
          [
            ["pipeline", "Pipeline", openOpps.length, false],
            ["leads", "Leads", leads.filter((l) => l.status !== "Converted").length, false],
            ["followups", "Follow-ups", overdue.length || activities.length, overdue.length > 0],
          ] as const
        ).map(([key, label, count, alarm]) => (
          <button key={key} role="tab" aria-selected={tab === key} className={tab === key ? "on" : ""} onClick={() => setTab(key)}>
            {label} <span className={`pill${alarm ? " bad" : ""}`}>{count}</span>
          </button>
        ))}
      </div>

      <ErrorNote message={error ?? loadError} />

      <div className="toolbar">
          <div className="filters" aria-label="Owner filter">
            {(["all", "mine", "unassigned"] as const).map((f) => (
              <button key={f} className={owner === f ? "on" : ""} onClick={() => setOwner(f)}>
                {f === "all" ? "Everyone" : f === "mine" ? "Mine" : "Unassigned"}
              </button>
            ))}
          </div>
      </div>

      {tab === "pipeline" && (
        <Pipeline
          opportunities={byOwner(opportunities, owner, user?.id)}
          onOpen={openOpp}
        />
      )}

      {tab === "leads" && (
        <LeadsTable
          leads={byOwner(leads, owner, user?.id)}
          canWrite={canWrite}
          canAssign={canAssign}
          assignees={assignees}
          onAssign={(l, id) => run(() => crm.assignLead(l.id, id))}
          onStatus={(l, s) => run(() => crm.setLeadStatus(l.id, s))}
          onConvert={(l) => setModal({ kind: "convert", lead: l })}
          onFollowUp={(l) => setModal({ kind: "followup", lead_id: l.id, name: l.organization || l.name })}
          onOpenOpp={openOpp}
        />
      )}

      {tab === "followups" && (
        <FollowUps
          rows={byOwner(activities, owner, user?.id)}
          canWrite={canWrite}
          onDone={(id) => run(() => crm.completeActivity(id))}
          onOpenOpp={openOpp}
        />
      )}

      {openOppId && <OpportunityDrawer opportunityId={openOppId} onClose={() => openOpp(null)} />}

      {modal?.kind === "lead" && (
        <NewLeadModal
          assignees={assignees}
          canAssign={canAssign}
          currentUserId={user?.id}
          onClose={() => setModal(null)}
          onSaved={async () => {
            setModal(null);
            await refresh();
            setTab("leads");
          }}
        />
      )}
      {modal?.kind === "opp" && (
        <NewOpportunityModal
          assignees={assignees}
          canAssign={canAssign}
          currentUserId={user?.id}
          onClose={() => setModal(null)}
          onSaved={async (opp) => {
            setModal(null);
            await refresh();
            openOpp(opp.id);
          }}
        />
      )}
      {modal?.kind === "convert" && (
        <ConvertLeadModal
          lead={modal.lead}
          onClose={() => setModal(null)}
          onSaved={async (opp) => {
            setModal(null);
            await refresh();
            openOpp(opp.id);
          }}
        />
      )}
      {modal?.kind === "followup" && (
        <FollowUpModal
          target={modal}
          onClose={() => setModal(null)}
          onSaved={async () => {
            setModal(null);
            await refresh();
          }}
        />
      )}
    </section>
  );
}

function Pipeline({ opportunities, onOpen }: { opportunities: Opportunity[]; onOpen: (id: string) => void }) {
  const closed = opportunities.filter((o) => !BOARD.includes(o.stage));
  return (
    <>
      <div className="pipeline">
        {BOARD.map((stage) => {
          const deals = opportunities.filter((o) => o.stage === stage);
          return (
            <div className="stage-col" key={stage}>
              <h4>
                {stage} <span>{inrShort(deals.reduce((s, o) => s + o.expected_value, 0))}</span>
              </h4>
              {deals.length === 0 && <p className="card-note">No deals</p>}
              {deals.map((o) => (
                <button key={o.id} className={`deal-card${o.overdue_activities ? " overdue" : ""}`} onClick={() => onOpen(o.id)}>
                  <b>{o.title}</b>
                  <span className="card-note">{o.customer_name}</span>
                  <div className="meta">
                    <span className="num" style={{ fontWeight: 700, color: "var(--ink)" }}>
                      {inrShort(o.expected_value)}
                    </span>
                    <span>{o.owner_name ?? <span style={{ color: "var(--warn)" }}>Unassigned</span>}</span>
                  </div>
                  <div className="meta">
                    <FollowUpBadge overdue={o.overdue_activities} open={o.open_activities} nextDueAt={o.next_due_at} />
                    {o.quotations.length > 0 && (
                      <span className="badge accent">
                        {o.quotations.length} quote{o.quotations.length === 1 ? "" : "s"}
                      </span>
                    )}
                  </div>
                </button>
              ))}
            </div>
          );
        })}
      </div>
      {closed.length > 0 && (
        <div className="closed-strip">
          {closed.map((o) => (
            <button key={o.id} className="ghost-btn sm" onClick={() => onOpen(o.id)}>
              <span className={`badge ${o.stage === "Won" ? "good" : "muted"}`}>{o.stage}</span> {o.title} · {inrShort(o.expected_value)}
            </button>
          ))}
        </div>
      )}
    </>
  );
}

function LeadsTable({
  leads,
  canWrite,
  canAssign,
  assignees,
  onAssign,
  onStatus,
  onConvert,
  onFollowUp,
  onOpenOpp,
}: {
  leads: Lead[];
  canWrite: boolean;
  canAssign: boolean;
  assignees: { id: string; display_name: string }[];
  onAssign: (lead: Lead, ownerId: string | null) => void;
  onStatus: (lead: Lead, status: LeadStatus) => void;
  onConvert: (lead: Lead) => void;
  onFollowUp: (lead: Lead) => void;
  onOpenOpp: (id: string) => void;
}) {
  if (leads.length === 0) return <div className="card empty-state">No leads match this filter.</div>;
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Lead</th>
            <th>Source</th>
            <th>Status</th>
            <th>Owner</th>
            <th>Next follow-up</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {leads.map((l) => (
            <tr key={l.id}>
              <td>
                <b>{l.organization || l.name}</b>
                <span className="sub">
                  {l.organization ? l.name : ""}
                  {l.phone ? ` · ${l.phone}` : ""}
                </span>
              </td>
              <td>{l.source}</td>
              <td>
                {l.status === "Converted" ? (
                  <span className="badge good">Converted</span>
                ) : (
                  <select
                    className="select-sm"
                    value={l.status}
                    disabled={!canWrite}
                    aria-label="Lead status"
                    onChange={(e) => onStatus(l, e.target.value as LeadStatus)}
                  >
                    {LEAD_STATUSES.filter((s) => s !== "Converted").map((s) => (
                      <option key={s}>{s}</option>
                    ))}
                  </select>
                )}
              </td>
              <td>
                <OwnerPicker value={l.owner_id} assignees={assignees} canAssign={canAssign && l.status !== "Converted"} onChange={(id) => onAssign(l, id)} />
              </td>
              <td>
                <FollowUpBadge overdue={l.overdue_activities} open={l.open_activities} nextDueAt={l.next_due_at} />
              </td>
              <td style={{ textAlign: "right" }}>
                {l.status === "Converted" && l.converted_opportunity_id ? (
                  <button className="link-btn" onClick={() => onOpenOpp(l.converted_opportunity_id!)}>
                    Open deal <Icon name="right" size={14} />
                  </button>
                ) : (
                  canWrite && (
                    <span style={{ display: "inline-flex", gap: 6 }}>
                      <button className="ghost-btn sm" onClick={() => onFollowUp(l)}>
                        Follow-up
                      </button>
                      <button className="primary-btn sm" disabled={l.status === "Lost"} onClick={() => onConvert(l)}>
                        Convert
                      </button>
                    </span>
                  )
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function FollowUps({
  rows,
  canWrite,
  onDone,
  onOpenOpp,
}: {
  rows: ReturnType<typeof useAppData>["activities"];
  canWrite: boolean;
  onDone: (id: string) => void;
  onOpenOpp: (id: string) => void;
}) {
  if (rows.length === 0) return <div className="card empty-state">Nothing scheduled. You're clear.</div>;
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Due</th>
            <th>Follow-up</th>
            <th>For</th>
            <th>Owner</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {rows.map((a) => (
            <tr key={a.id} className={`activity-row${a.is_overdue ? " overdue" : ""}`}>
              <td>
                <span className={`followup${a.is_overdue ? " overdue" : ""}`}>
                  <Icon name={a.is_overdue ? "alert" : "clock"} size={14} /> {relativeDue(a.due_at)}
                </span>
                <span className="sub">{dateTime(a.due_at)}</span>
              </td>
              <td>
                <b>{a.subject}</b>
                <span className="sub">{a.kind}</span>
              </td>
              <td>
                {a.opportunity_id ? (
                  <button className="link-btn" onClick={() => onOpenOpp(a.opportunity_id!)}>
                    {a.related_name}
                  </button>
                ) : (
                  <>
                    {a.related_name} <span className="badge muted">Lead</span>
                  </>
                )}
              </td>
              <td>{a.owner_name ?? "—"}</td>
              <td style={{ textAlign: "right" }}>
                {canWrite && (
                  <button className="ghost-btn sm" onClick={() => onDone(a.id)}>
                    <Icon name="check" size={14} /> Done
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
