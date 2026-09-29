import { useState } from "react";
import { ApiError, assignOpportunity, updateActivity, updateOpportunity, type OpportunityStage } from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import { Icon } from "../components/Icon";
import { useAppData } from "../data/AppDataProvider";
import { dateTime, inr, quoteStatusClass, relativeDue } from "../lib/format";
import { FollowUpModal, QuoteForm } from "./forms";
import { Drawer, ErrorNote, FollowUpBadge, OwnerPicker } from "./ui";

const OPEN_FLOW: OpportunityStage[] = ["New", "Qualified", "Proposal", "Negotiation"];

/** One opportunity end to end: stage, owner, follow-ups, and its quotations. */
export function OpportunityDrawer({ opportunityId, onClose }: { opportunityId: string; onClose: () => void }) {
  const { opportunities, activities, assignees, items, refresh, can } = useAppData();
  const { user } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [followUpOpen, setFollowUpOpen] = useState(false);

  const opp = opportunities.find((o) => o.id === opportunityId);
  if (!opp) return null;

  const canWrite = can("crm.opportunity.write");
  const canLog = can("crm.activity.write");
  const canQuote = can("sales.quotation.create");
  const isOpen = OPEN_FLOW.includes(opp.stage);
  const followUps = activities.filter((a) => a.opportunity_id === opp.id);
  const currentIdx = OPEN_FLOW.indexOf(opp.stage);

  async function run(action: () => Promise<unknown>, ok?: string) {
    setError(null);
    setNotice(null);
    try {
      await action();
      await refresh();
      if (ok) setNotice(ok);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not reach the Albiruni API.");
    }
  }

  return (
    <Drawer
      title={opp.name}
      subtitle={
        <>
          {opp.customer_name} · {inr(opp.value)} · {opp.probability_pct}% likely
          {opp.expected_close_date ? ` · closes ${new Date(opp.expected_close_date).toLocaleDateString("en-IN", { day: "numeric", month: "short" })}` : ""}
        </>
      }
      onClose={onClose}
    >
      <ErrorNote message={error} />
      {notice && <div className="notice good">{notice}</div>}

      <div className="card">
        <div className="card-head">
          <span className="card-title">Stage</span>
          <FollowUpBadge overdue={opp.overdue_activities} open={opp.open_activities} nextDueAt={opp.next_due_at} />
        </div>
        <div className="stage-steps">
          {OPEN_FLOW.map((s, i) => (
            <button
              key={s}
              disabled={!canWrite}
              className={opp.stage === s ? "on" : isOpen && i < currentIdx ? "done" : ""}
              onClick={() => run(() => updateOpportunity(opp.id, { stage: s }))}
            >
              {s}
            </button>
          ))}
        </div>
        <div className="stage-steps" style={{ marginTop: 8 }}>
          {(["Won", "Lost"] as const).map((s) => (
            <button
              key={s}
              disabled={!canWrite}
              className={`${s === "Lost" ? "lost " : ""}${opp.stage === s ? "on" : ""}`}
              onClick={() => run(() => updateOpportunity(opp.id, { stage: s }))}
            >
              {s === "Won" ? "✓ Won" : "✕ Lost"}
            </button>
          ))}
        </div>
        <div className="fields" style={{ marginTop: 16 }}>
          <div className="field">
            Owner
            <OwnerPicker
              value={opp.owner_user_id}
              assignees={assignees}
              canAssign={can("crm.opportunity.assign")}
              onChange={(id) => run(() => assignOpportunity(opp.id, id), id ? "Owner updated." : "Unassigned.")}
            />
          </div>
          <div className="field">
            Came from
            <span className="static">{opp.lead_id ? "Converted lead" : "Created directly"}</span>
          </div>
        </div>
      </div>

      <div className="card">
        <div className="card-head">
          <span className="card-title">Quotations ({opp.quotations.length})</span>
        </div>
        {opp.quotations.length === 0 ? (
          <p className="card-note" style={{ margin: 0 }}>
            None yet. A quotation raised here is linked to this opportunity and moves it to Proposal.
          </p>
        ) : (
          <div className="mini-list">
            {opp.quotations.map((q) => (
              <div className="row" key={q.id}>
                <Icon name="file" size={18} />
                <div className="grow">
                  <b className="mono">{q.number}</b>
                  <small>
                    {q.lines.length} line{q.lines.length === 1 ? "" : "s"} · {dateTime(q.created_at)}
                    {q.discount_pct ? ` · ${q.discount_pct}% off` : ""}
                  </small>
                </div>
                <span className={`badge ${quoteStatusClass(q.status)}`}>{q.status}</span>
                <b className="num">{inr(q.total)}</b>
              </div>
            ))}
          </div>
        )}
        {isOpen && canQuote && (
          <div style={{ marginTop: 16, paddingTop: 16, borderTop: "1px solid var(--line)" }}>
            <div className="card-title" style={{ fontSize: 14.5, marginBottom: 10 }}>
              New quotation
            </div>
            <QuoteForm
              opportunity={opp}
              items={items}
              onCreated={async (r) => {
                await refresh();
                setNotice(
                  `${r.number} created — ${inr(r.total)}${r.requires_approval ? ", sent for approval" : ""}.` +
                    (r.warnings.length ? ` ${r.warnings.join(" ")}` : ""),
                );
              }}
            />
          </div>
        )}
        {!isOpen && (
          <p className="card-note" style={{ marginBottom: 0 }}>
            This opportunity is {opp.stage}. Move it back to an open stage to quote again.
          </p>
        )}
      </div>

      <div className="card">
        <div className="card-head">
          <span className="card-title">Follow-ups</span>
          {canLog && (
            <button className="ghost-btn sm" onClick={() => setFollowUpOpen(true)}>
              <Icon name="plus" size={14} /> Schedule
            </button>
          )}
        </div>
        {followUps.length === 0 ? (
          <p className="card-note" style={{ margin: 0 }}>
            No open follow-ups. Deals without a next step are the ones that go quiet.
          </p>
        ) : (
          <div className="mini-list">
            {followUps.map((a) => (
              <div className={`row${a.is_overdue ? " overdue" : ""}`} key={a.id}>
                <Icon name={a.type === "Call" ? "phone" : a.type === "Meeting" ? "users" : a.type === "Email" ? "send" : "check"} size={18} />
                <div className="grow">
                  {a.subject}
                  <small>
                    {a.type}
                    {a.due_at ? ` · ${dateTime(a.due_at)} · ${relativeDue(a.due_at)}` : " · no due date"}
                    {a.owner_name && a.owner_id !== user?.id ? ` · ${a.owner_name}` : ""}
                  </small>
                </div>
                {canLog && (
                  <button className="ghost-btn sm" onClick={() => run(() => updateActivity(a.id, { done: true }), "Follow-up marked done.")}>
                    Done
                  </button>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {followUpOpen && (
        <FollowUpModal
          target={{ opportunity_id: opp.id, name: opp.name }}
          onClose={() => setFollowUpOpen(false)}
          onSaved={async () => {
            setFollowUpOpen(false);
            await refresh();
          }}
        />
      )}
    </Drawer>
  );
}
