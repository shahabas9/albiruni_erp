import { useEffect, useState, type DragEvent, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import {
  ApiError,
  fetchOpportunities,
  fetchStaleLimits,
  saveStaleLimits,
  updateOpportunity,
  type Opportunity,
  type OpportunityStage,
  type StaleLimits,
} from "../api/client";
import { Icon } from "../components/Icon";
import { useOpenOpportunity } from "../crm/drawerHost";
import { LostReasonModal } from "../crm/forms";
import { ErrorNote, FollowUpBadge, IdleBadge, Modal } from "../crm/ui";
import { useAppData } from "../data/AppDataProvider";
import { inrShort } from "../lib/format";

type OwnerFilter = "all" | "mine" | "unassigned";

const BOARD: OpportunityStage[] = ["New", "Qualified", "Proposal", "Negotiation"];
// The board shows every open deal plus those closed in this window; older
// closed deals live on the Opportunities list.
const CLOSED_WINDOW_DAYS = 90;

function isoDaysAgo(days: number) {
  const d = new Date();
  d.setDate(d.getDate() - days);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

const weighted = (o: Opportunity) => (o.value * o.probability_pct) / 100;
const sum = (rows: Opportunity[], f: (o: Opportunity) => number) => rows.reduce((s, o) => s + f(o), 0);

function isThisMonth(iso: string, now = new Date()) {
  const d = new Date(iso);
  return d.getFullYear() === now.getFullYear() && d.getMonth() === now.getMonth();
}

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
  const [opportunities, setOpportunities] = useState<Opportunity[]>([]);
  const [editingLimits, setEditingLimits] = useState(false);

  useEffect(() => {
    let current = true;
    fetchOpportunities({ closed_since: isoDaysAgo(CLOSED_WINDOW_DAYS), owner: owner === "all" ? "" : owner })
      .then((page) => current && (setOpportunities(page.rows), setLoadError(null)))
      .catch((err) => current && setLoadError(err instanceof ApiError ? err.message : "Couldn't load the pipeline."));
    return () => {
      current = false;
    };
  }, [owner, version]);

  const canMove = can("crm.opportunity.write");
  const open = opportunities.filter((o) => BOARD.includes(o.stage));
  const won = opportunities.filter((o) => o.stage === "Won");
  const lost = opportunities.filter((o) => o.stage === "Lost");
  const stale = open.filter((o) => o.is_stale);
  const overdue = crm?.overdue_followups ?? 0;
  const winRate = won.length + lost.length ? Math.round((won.length / (won.length + lost.length)) * 100) : null;

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
      const opp = opportunities.find((o) => o.id === e.dataTransfer.getData("text/plain"));
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
        <Stat label="Open pipeline" value={inrShort(sum(open, (o) => o.value))} sub={`${open.length} open deal${open.length === 1 ? "" : "s"}`} />
        <Stat label="Weighted forecast" value={inrShort(sum(open, weighted))} sub="Each deal's value × its probability" />
        <Stat
          label="Won this month"
          value={inrShort(sum(won.filter((o) => isThisMonth(o.stage_changed_at)), (o) => o.value))}
          sub={winRate === null ? `No deals closed in ${CLOSED_WINDOW_DAYS} days` : `${winRate}% win rate, last ${CLOSED_WINDOW_DAYS} days`}
        />
        <Stat
          label="Going stale"
          value={String(stale.length)}
          sub={stale.length ? `${inrShort(sum(stale, (o) => o.value))} not touched recently` : "Every open deal has recent activity"}
          tone={stale.length ? "warn" : undefined}
          action={
            <button className="link-btn" style={{ padding: 0 }} onClick={() => setEditingLimits(true)}>
              {can("crm.settings.write") ? "Set limits" : "See limits"}
            </button>
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
          const deals = open.filter((o) => o.stage === stage);
          return (
            <div className={`stage-col${overStage === stage ? " drop-over" : ""}`} key={stage} {...dropZone(stage)}>
              <h4>
                {stage} <span>{inrShort(sum(deals, (o) => o.value))}</span>
              </h4>
              <div className="stage-weighted">Weighted {inrShort(sum(deals, weighted))}</div>
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

      <WinLoss won={won} lost={lost} onOpen={openOpp} />

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

const LIMIT_HINTS: Record<keyof StaleLimits, string> = {
  New: "A fresh deal nobody has called",
  Qualified: "Qualified, but no proposal yet",
  Proposal: "Quote sent, waiting on the customer",
  Negotiation: "Closing — goes cold fastest",
};

/** Per-company "going stale" limits: days a deal may sit untouched in each stage. */
function StaleLimitsModal({ canEdit, onClose, onSaved }: { canEdit: boolean; onClose: () => void; onSaved: () => void }) {
  const [limits, setLimits] = useState<StaleLimits | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    fetchStaleLimits()
      .then(setLimits)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Couldn't load the limits."));
  }, []);

  async function save() {
    if (!limits) return;
    setSaving(true);
    setError(null);
    try {
      await saveStaleLimits(limits);
      onSaved();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't save.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal
      title="When is a deal going stale?"
      onClose={onClose}
      footer={
        canEdit ? (
          <>
            <button type="button" className="ghost-btn" onClick={onClose}>
              Cancel
            </button>
            <button className="primary-btn" disabled={!limits || saving} onClick={save}>
              {saving ? "Saving…" : "Save for the company"}
            </button>
          </>
        ) : (
          <button className="primary-btn" onClick={onClose}>
            Close
          </button>
        )
      }
    >
      <p className="card-note" style={{ marginTop: 0 }}>
        A deal is flagged when nothing — a call, a follow-up, a quotation or a stage change — has touched it for this many days.
        Use 0 to never flag a stage.{!canEdit && " Changing these needs the crm.settings.write permission."}
      </p>
      {limits && (
        <div className="limits-grid">
          {BOARD.map((stage) => {
            const key = stage as keyof StaleLimits;
            return (
              <label className="field" key={stage}>
                <span>{stage}</span>
                <div className="input-suffix">
                  <input
                    type="number"
                    min={0}
                    max={365}
                    value={limits[key]}
                    disabled={!canEdit}
                    onChange={(e) => setLimits({ ...limits, [key]: Math.max(0, Math.min(365, Number(e.target.value) || 0)) })}
                  />
                  <span>{limits[key] === 0 ? "off" : "days"}</span>
                </div>
                <small>{LIMIT_HINTS[key]}</small>
              </label>
            );
          })}
        </div>
      )}
      <ErrorNote message={error} />
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
function WinLoss({ won, lost, onOpen }: { won: Opportunity[]; lost: Opportunity[]; onOpen: (id: string) => void }) {
  if (won.length + lost.length === 0) return null;
  const reasons = new Map<string, number>();
  for (const o of lost) {
    const key = o.lost_reason || "No reason recorded";
    reasons.set(key, (reasons.get(key) ?? 0) + 1);
  }
  const rows = [...reasons.entries()].sort((a, b) => b[1] - a[1]);
  const max = Math.max(...rows.map(([, n]) => n), 1);

  return (
    <div className="overview-row even" style={{ marginTop: 20 }}>
      <div className="card">
        <div className="card-head">
          <span className="card-title">Why deals are lost</span>
          <span className="card-note">
            {lost.length} lost · {inrShort(sum(lost, (o) => o.value))}
          </span>
        </div>
        {rows.length === 0 ? (
          <p className="card-note" style={{ margin: 0 }}>No lost deals yet.</p>
        ) : (
          <div className="bars">
            {rows.map(([reason, n]) => (
              <div className="bar-row" key={reason}>
                <span className="label" title={reason}>
                  {reason}
                </span>
                <div className="track">
                  <div className="fill lost-fill" style={{ width: `${(n / max) * 100}%` }} />
                </div>
                <span className="value num">{n}</span>
              </div>
            ))}
          </div>
        )}
      </div>
      <div className="card">
        <div className="card-head">
          <span className="card-title">Recently closed</span>
          <span className="card-note">
            {won.length} won · {inrShort(sum(won, (o) => o.value))}
          </span>
        </div>
        <div className="mini-list">
          {[...won, ...lost]
            .sort((a, b) => b.stage_changed_at.localeCompare(a.stage_changed_at))
            .slice(0, 6)
            .map((o) => (
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
