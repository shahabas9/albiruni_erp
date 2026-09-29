import { useEffect, useState, type DragEvent, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import {
  ApiError,
  fetchCrmSummary,
  fetchOpportunities,
  updateOpportunity,
  type CrmSummary,
  type Opportunity,
  type OpportunityStage,
  type Page,
} from "../api/client";
import { Icon } from "../components/Icon";
import { useOpenOpportunity } from "../crm/drawerHost";
import { LostReasonModal } from "../crm/forms";
import { StaleLimitsEditor } from "../crm/StaleLimitsEditor";
import { ErrorNote, FollowUpBadge, IdleBadge, Modal, ownerParam, type OwnerFilter } from "../crm/ui";
import { useAppData } from "../data/AppDataProvider";
import { inrShort } from "../lib/format";

const BOARD: OpportunityStage[] = ["New", "Qualified", "Proposal", "Negotiation"];
// Each column shows its newest deals; totals and the rest come from the
// server, so the board costs the same with 50 open deals or 50,000.
const COLUMN_LIMIT = 30;
// Win/loss figures cover deals closed in this window.
const CLOSED_WINDOW_DAYS = 90;

type Columns = Partial<Record<OpportunityStage, Page<Opportunity>>>;

/** The pipeline board: drag deals between stages, drop on Won/Lost to close them. */
export function Crm() {
  const { crm, version, refresh, can } = useAppData();
  const openOpp = useOpenOpportunity();
  const navigate = useNavigate();
  const [owner, setOwner] = useState<OwnerFilter>("all");
  const [dragId, setDragId] = useState<string | null>(null);
  const [overStage, setOverStage] = useState<OpportunityStage | null>(null);
  const [losing, setLosing] = useState<Opportunity | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [columns, setColumns] = useState<Columns>({});
  const [board, setBoard] = useState<CrmSummary | null>(null);
  const [editingLimits, setEditingLimits] = useState(false);

  useEffect(() => {
    let current = true;
    const ownerArg = ownerParam(owner);
    Promise.all([
      fetchCrmSummary({ owner: ownerArg, closed_days: CLOSED_WINDOW_DAYS }),
      ...BOARD.map((stage) => fetchOpportunities({ stage, owner: ownerArg, limit: COLUMN_LIMIT })),
    ])
      .then(([summary, ...pages]) => {
        if (!current) return;
        setBoard(summary as CrmSummary);
        setColumns(Object.fromEntries(BOARD.map((stage, i) => [stage, pages[i] as Page<Opportunity>])));
        setLoadError(null);
      })
      .catch((err) => current && setLoadError(err instanceof ApiError ? err.message : "Couldn't load the pipeline."));
    return () => {
      current = false;
    };
  }, [owner, version]);

  const canMove = can("crm.opportunity.write");
  const shown = BOARD.flatMap((stage) => columns[stage]?.rows ?? []);
  const stageTotal = (stage: OpportunityStage) => board?.by_stage.find((b) => b.stage === stage);
  const overdue = crm?.overdue_followups ?? 0;
  const closedCount = (board?.recent_won ?? 0) + (board?.recent_lost ?? 0);
  const winRate = closedCount ? Math.round(((board?.recent_won ?? 0) / closedCount) * 100) : null;
  const staleCount = board?.stale_deals ?? 0;

  async function move(opp: Opportunity, stage: OpportunityStage) {
    if (opp.stage === stage) return;
    if (stage === "Lost") {
      setLosing(opp);
      return;
    }
    setError(null);
    try {
      await updateOpportunity(opp.id, { stage });
      await refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't move the deal.");
    }
  }

  const dropZone = (stage: OpportunityStage) => ({
    onDragOver: (e: DragEvent) => {
      if (!dragId) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = "move";
      setOverStage(stage);
    },
    onDragLeave: () => setOverStage((s) => (s === stage ? null : s)),
    onDrop: (e: DragEvent) => {
      e.preventDefault();
      const opp = shown.find((o) => o.id === e.dataTransfer.getData("text/plain"));
      setDragId(null);
      setOverStage(null);
      if (opp) void move(opp, stage);
    },
  });

  return (
    <section>
      <div className="page-head">
        <div>
          <h1 className="page-title">Pipeline</h1>
          <p className="page-sub">
            {canMove ? "Drag a deal to another stage, or onto Won / Lost to close it." : "Deals by stage."}
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
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {can("crm.lead.write") && (
            <button className="ghost-btn" onClick={() => navigate("/leads?new=1")}>
              <Icon name="plus" size={16} /> Lead
            </button>
          )}
          {can("crm.opportunity.write") && (
            <button className="primary-btn" onClick={() => navigate("/opportunities?new=1")}>
              <Icon name="plus" size={16} /> Opportunity
            </button>
          )}
        </div>
      </div>

      <div className="forecast-strip">
        <Stat
          label="Open pipeline"
          value={inrShort(board?.open_value ?? 0)}
          sub={`${board?.open_deals ?? 0} open deal${board?.open_deals === 1 ? "" : "s"}`}
        />
        <Stat label="Weighted forecast" value={inrShort(board?.weighted_value ?? 0)} sub="Each deal's value × its probability" />
        <Stat
          label="Won this month"
          value={inrShort(board?.won_this_month_value ?? 0)}
          sub={winRate === null ? `No deals closed in ${CLOSED_WINDOW_DAYS} days` : `${winRate}% win rate, last ${CLOSED_WINDOW_DAYS} days`}
        />
        <Stat
          label="Going stale"
          value={String(staleCount)}
          sub={staleCount ? `${inrShort(board?.stale_value ?? 0)} not touched recently` : "Every open deal has recent activity"}
          tone={staleCount ? "warn" : undefined}
          action={
            <span style={{ display: "inline-flex", gap: 12 }}>
              {staleCount > 0 && (
                <button className="link-btn" style={{ padding: 0 }} onClick={() => navigate("/opportunities?stale=1")}>
                  See them
                </button>
              )}
              <button className="link-btn" style={{ padding: 0 }} onClick={() => setEditingLimits(true)}>
                {can("crm.settings.write") ? "Set limits" : "See limits"}
              </button>
            </span>
          }
        />
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

      <div className="pipeline">
        {BOARD.map((stage) => {
          const deals = columns[stage]?.rows ?? [];
          const total = stageTotal(stage);
          const more = (columns[stage]?.total ?? 0) - deals.length;
          return (
            <div className={`stage-col${overStage === stage ? " drop-over" : ""}`} key={stage} {...dropZone(stage)}>
              <h4>
                {stage} <span>{inrShort(total?.value ?? 0)}</span>
              </h4>
              <div className="stage-weighted">
                {total?.count ?? 0} deal{total?.count === 1 ? "" : "s"} · weighted {inrShort(total?.weighted ?? 0)}
              </div>
              {deals.length === 0 && <p className="card-note">{dragId ? "Drop here" : "No deals"}</p>}
              {deals.map((o) => (
                <DealCard
                  key={o.id}
                  opp={o}
                  draggable={canMove}
                  dragging={dragId === o.id}
                  onOpen={() => openOpp(o.id)}
                  onDragStart={(e) => {
                    e.dataTransfer.setData("text/plain", o.id);
                    e.dataTransfer.effectAllowed = "move";
                    setDragId(o.id);
                  }}
                  onDragEnd={() => {
                    setDragId(null);
                    setOverStage(null);
                  }}
                />
              ))}
              {more > 0 && (
                <button className="link-btn column-more" onClick={() => navigate(`/opportunities?stage=${stage}`)}>
                  +{more} more in {stage} — see all
                </button>
              )}
            </div>
          );
        })}
      </div>

      {canMove && (
        <div className={`close-zones${dragId ? " active" : ""}`}>
          <div className={`close-zone won${overStage === "Won" ? " drop-over" : ""}`} {...dropZone("Won")}>
            <Icon name="check" /> Drop to mark <b>Won</b>
          </div>
          <div className={`close-zone lost${overStage === "Lost" ? " drop-over" : ""}`} {...dropZone("Lost")}>
            <Icon name="x" /> Drop to mark <b>Lost</b>
          </div>
        </div>
      )}

      {board && <WinLoss summary={board} onOpen={openOpp} />}

      {editingLimits && (
        <StaleLimitsModal
          canEdit={can("crm.settings.write")}
          onClose={() => setEditingLimits(false)}
          onSaved={async () => {
            setEditingLimits(false);
            await refresh();
          }}
        />
      )}

      {losing && (
        <LostReasonModal
          dealName={losing.name}
          onClose={() => setLosing(null)}
          onConfirm={async (reason) => {
            await updateOpportunity(losing.id, { stage: "Lost", lost_reason: reason });
            setLosing(null);
            await refresh();
          }}
        />
      )}
    </section>
  );
}

function Stat({
  label,
  value,
  sub,
  tone,
  action,
}: {
  label: string;
  value: string;
  sub: string;
  tone?: "warn";
  action?: ReactNode;
}) {
  return (
    <div className={`card stat${tone ? ` ${tone}` : ""}`}>
      <div className="stat-label">{label}</div>
      <div className="stat-value num">{value}</div>
      <div className="stat-sub">{sub}</div>
      {action && <div className="stat-action">{action}</div>}
    </div>
  );
}

/** Per-company "going stale" limits, in a dialog. */
function StaleLimitsModal({ canEdit, onClose, onSaved }: { canEdit: boolean; onClose: () => void; onSaved: () => void }) {
  return (
    <Modal title="When is a deal going stale?" onClose={onClose}>
      <StaleLimitsEditor canEdit={canEdit} onSaved={onSaved} onCancel={onClose} />
    </Modal>
  );
}

function DealCard({
  opp: o,
  draggable,
  dragging,
  onOpen,
  onDragStart,
  onDragEnd,
}: {
  opp: Opportunity;
  draggable: boolean;
  dragging: boolean;
  onOpen: () => void;
  onDragStart: (e: DragEvent) => void;
  onDragEnd: () => void;
}) {
  return (
    <div
      role="button"
      tabIndex={0}
      className={`deal-card${o.overdue_activities ? " overdue" : ""}${o.is_stale ? " stale" : ""}${dragging ? " dragging" : ""}`}
      draggable={draggable}
      onDragStart={onDragStart}
      onDragEnd={onDragEnd}
      onClick={onOpen}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onOpen();
        }
      }}
      aria-label={`${o.name}, ${o.customer_name}. Open deal`}
    >
      <b>{o.name}</b>
      <span className="card-note">{o.customer_name}</span>
      <div className="meta">
        <span className="num" style={{ fontWeight: 700, color: "var(--ink)" }}>
          {inrShort(o.value)} <span style={{ fontWeight: 500, color: "var(--ink-faint)" }}>· {o.probability_pct}%</span>
        </span>
        <span>{o.owner_name ?? <span style={{ color: "var(--warn)" }}>Unassigned</span>}</span>
      </div>
      <div className="meta">
        {o.is_stale ? (
          <IdleBadge days={o.idle_days} />
        ) : (
          <FollowUpBadge overdue={o.overdue_activities} open={o.open_activities} nextDueAt={o.next_due_at} />
        )}
        {o.quotations.length > 0 && (
          <span className="badge accent">
            {o.quotations.length} quote{o.quotations.length === 1 ? "" : "s"}
          </span>
        )}
      </div>
    </div>
  );
}

/** Closed deals and, for lost ones, why — the point of recording a reason. */
function WinLoss({ summary, onOpen }: { summary: CrmSummary; onOpen: (id: string) => void }) {
  if (summary.recent_won + summary.recent_lost === 0) return null;
  const max = Math.max(...summary.lost_reasons.map((r) => r.count), 1);
  const days = summary.closed_days;

  return (
    <div className="overview-row even" style={{ marginTop: 20 }}>
      <div className="card">
        <div className="card-head">
          <span className="card-title">Why deals are lost</span>
          <span className="card-note">
            {summary.recent_lost} lost · {inrShort(summary.recent_lost_value)} · last {days} days
          </span>
        </div>
        {summary.lost_reasons.length === 0 ? (
          <p className="card-note" style={{ margin: 0 }}>No lost deals in the last {days} days.</p>
        ) : (
          <div className="bars">
            {summary.lost_reasons.map(({ reason, count }) => (
              <div className="bar-row" key={reason}>
                <span className="label" title={reason}>
                  {reason}
                </span>
                <div className="track">
                  <div className="fill lost-fill" style={{ width: `${(count / max) * 100}%` }} />
                </div>
                <span className="value num">{count}</span>
              </div>
            ))}
          </div>
        )}
      </div>
      <div className="card">
        <div className="card-head">
          <span className="card-title">Recently closed</span>
          <span className="card-note">
            {summary.recent_won} won · {inrShort(summary.recent_won_value)}
          </span>
        </div>
        <div className="mini-list">
          {summary.recently_closed.map((o) => (
            <div className="row" key={o.id}>
              <span className={`badge ${o.stage === "Won" ? "good" : "bad"}`}>{o.stage}</span>
              <div className="grow">
                <button className="link-btn" style={{ padding: 0 }} onClick={() => onOpen(o.id)}>
                  {o.name}
                </button>
                <small>{o.stage === "Lost" ? o.lost_reason || "No reason recorded" : o.customer_name}</small>
              </div>
              <b className="num">{inrShort(o.value)}</b>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
