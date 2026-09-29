import { useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  type CrmOpportunity as Opportunity,
  type CrmOpportunityStage as OpportunityStage,
} from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import { Icon } from "../components/Icon";
import { useOpenOpportunity } from "../crm/drawerHost";
import { NewLeadModal, NewOpportunityModal } from "../crm/forms";
import { ErrorNote, FollowUpBadge } from "../crm/ui";
import { useAppData } from "../data/AppDataProvider";
import { inrShort } from "../lib/format";

type OwnerFilter = "all" | "mine" | "unassigned";

const BOARD: OpportunityStage[] = ["New", "Qualified", "Proposal", "Negotiation"];

function byOwner<T extends { owner_id: string | null }>(rows: T[], filter: OwnerFilter, me: string | undefined) {
  if (filter === "mine") return rows.filter((r) => r.owner_id === me);
  if (filter === "unassigned") return rows.filter((r) => !r.owner_id);
  return rows;
}

/** The pipeline board. Lead, opportunity and follow-up lists live on their own pages. */
export function Crm() {
  const { user } = useAuth();
  const { opportunities, activities, assignees, error, refresh, can } = useAppData();
  const openOpp = useOpenOpportunity();
  const navigate = useNavigate();
  const [owner, setOwner] = useState<OwnerFilter>("all");
  const [modal, setModal] = useState<"lead" | "opp" | null>(null);

  const openOpps = opportunities.filter((o) => BOARD.includes(o.stage));
  const overdue = activities.filter((a) => a.is_overdue).length;

  return (
    <section>
      <div className="page-head">
        <div>
          <h1 className="page-title">Pipeline</h1>
          <p className="page-sub">
            {openOpps.length} open deal{openOpps.length === 1 ? "" : "s"} worth{" "}
            {inrShort(openOpps.reduce((s, o) => s + o.expected_value, 0))}
            {overdue > 0 && (
              <>
                {" · "}
                <button className="link-btn" style={{ color: "var(--bad)", padding: 0 }} onClick={() => navigate("/activities?show=overdue")}>
                  {overdue} follow-up{overdue === 1 ? "" : "s"} overdue
                </button>
              </>
            )}
          </p>
        </div>
        {can("crm.write") && (
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <button className="ghost-btn" onClick={() => setModal("lead")}>
              <Icon name="plus" size={16} /> Lead
            </button>
            <button className="primary-btn" onClick={() => setModal("opp")}>
              <Icon name="plus" size={16} /> Opportunity
            </button>
          </div>
        )}
      </div>

      <ErrorNote message={error} />

      <div className="toolbar">
        <div className="filters" aria-label="Owner filter">
          {(["all", "mine", "unassigned"] as const).map((f) => (
            <button key={f} className={owner === f ? "on" : ""} onClick={() => setOwner(f)}>
              {f === "all" ? "Everyone" : f === "mine" ? "Mine" : "Unassigned"}
            </button>
          ))}
        </div>
      </div>

      <Pipeline opportunities={byOwner(opportunities, owner, user?.id)} onOpen={openOpp} />

      {modal === "lead" && (
        <NewLeadModal
          assignees={assignees}
          canAssign={can("crm.assign")}
          currentUserId={user?.id}
          onClose={() => setModal(null)}
          onSaved={async () => {
            setModal(null);
            await refresh();
            navigate("/leads");
          }}
        />
      )}
      {modal === "opp" && (
        <NewOpportunityModal
          assignees={assignees}
          canAssign={can("crm.assign")}
          currentUserId={user?.id}
          onClose={() => setModal(null)}
          onSaved={async (opp) => {
            setModal(null);
            await refresh();
            openOpp(opp.id);
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
