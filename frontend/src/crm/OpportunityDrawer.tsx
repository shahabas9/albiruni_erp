import { useEffect, useState } from "react";
import {
  ApiError,
  assignOpportunity,
  fetchActivities,
  fetchContacts,
  fetchOpportunity,
  fetchOpportunityTimeline,
  updateActivity,
  updateOpportunity,
  type Activity,
  type Contact,
  type Opportunity,
  type OpportunityStage,
} from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import { Icon } from "../components/Icon";
import { useAppData } from "../data/AppDataProvider";
import { dateTime, inr, quoteStatusClass, relativeDue, shortDate } from "../lib/format";
import { ContactActions } from "./ContactActions";
import { FollowUpModal, LostReasonModal, QuoteForm } from "./forms";
import { Timeline } from "./Timeline";
import { Drawer, ErrorNote, FollowUpBadge, IdleBadge, OwnerPicker } from "./ui";

const OPEN_FLOW: OpportunityStage[] = ["New", "Qualified", "Proposal", "Negotiation"];

/** One opportunity end to end: stage, owner, follow-ups, and its quotations. */
export function OpportunityDrawer({ opportunityId, onClose }: { opportunityId: string; onClose: () => void }) {
  const { version, assignees, items, refresh, can } = useAppData();
  const { user } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [followUpOpen, setFollowUpOpen] = useState(false);
  const [lostOpen, setLostOpen] = useState(false);
  const [opp, setOpp] = useState<Opportunity | null>(null);
  const [followUps, setFollowUps] = useState<Activity[]>([]);
  const canSeeFollowUps = can("crm.activity.read");

  // Fetched by id, so any deal opens — including ones closed long ago that
  // no list on screen has loaded. `version` refetches after every change.
  useEffect(() => {
    let current = true;
    Promise.all([
      fetchOpportunity(opportunityId),
      canSeeFollowUps ? fetchActivities({ opportunity_id: opportunityId, show: "open" }) : Promise.resolve(null),
    ])
      .then(([o, acts]) => {
        if (!current) return;
        setOpp(o);
        setFollowUps(acts?.rows ?? []);
      })
      .catch((err) => current && setError(err instanceof ApiError ? err.message : "Couldn't load this deal."));
    return () => {
      current = false;
    };
  }, [opportunityId, version, canSeeFollowUps]);

  const customerId = opp?.customer_id;
  const canSeeContacts = can("crm.contact.read");
  const [contacts, setContacts] = useState<Contact[]>([]);
  useEffect(() => {
    if (!customerId || !canSeeContacts) return;
    fetchContacts({ customer_id: customerId, limit: 50 })
      .then((page) => setContacts(page.rows))
      .catch(() => setContacts([]));
  }, [customerId, canSeeContacts]);
  if (!opp) {
    return error ? (
      <Drawer title="Deal" onClose={onClose}>
        <ErrorNote message={error} />
      </Drawer>
    ) : null;
  }

  const canWrite = can("crm.opportunity.write");
  const canLog = can("crm.activity.write");
  const canQuote = can("sales.quotation.create");
  const isOpen = OPEN_FLOW.includes(opp.stage);
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
          <span style={{ display: "inline-flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
            {opp.is_stale && <IdleBadge days={opp.idle_days} />}
            <FollowUpBadge overdue={opp.overdue_activities} open={opp.open_activities} nextDueAt={opp.next_due_at} />
          </span>
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
              onClick={() =>
                s === "Lost" && opp.stage !== "Lost" ? setLostOpen(true) : run(() => updateOpportunity(opp.id, { stage: s }))
              }
            >
              {s === "Won" ? "✓ Won" : "✕ Lost"}
            </button>
          ))}
        </div>
        {opp.stage === "Lost" && (
          <p className="card-note" style={{ margin: "10px 0 0" }}>
            Lost {shortDate(opp.stage_changed_at)} — <b style={{ color: "var(--bad)" }}>{opp.lost_reason || "no reason recorded"}</b>
          </p>
        )}
        {opp.stage === "Won" && (
          <p className="card-note" style={{ margin: "10px 0 0" }}>
            Won {shortDate(opp.stage_changed_at)}
          </p>
        )}
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

      {canSeeContacts && (
        <div className="card">
          <div className="card-head">
            <span className="card-title">People at {opp.customer_name}</span>
          </div>
          {contacts.length === 0 ? (
            <p className="card-note" style={{ margin: 0 }}>
              No contacts yet — add them on the Contacts page to call or WhatsApp from here.
            </p>
          ) : (
            <div className="mini-list">
              {contacts.map((c) => (
                <div className="row" key={c.id}>
                  <Icon name="user" size={18} />
                  <div className="grow">
                    {c.name}
                    <small>{[c.title, c.phone || "no phone"].filter(Boolean).join(" · ")}</small>
                  </div>
                  <ContactActions
                    phone={c.phone}
                    name={c.name}
                    target={{ opportunity_id: opp.id }}
                    onLogged={async () => {
                      await refresh();
                      setNotice(`Logged your contact with ${c.name}.`);
                    }}
                  />
                </div>
              ))}
            </div>
          )}
        </div>
      )}

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

      <div className="card">
        <div className="card-head">
          <span className="card-title">History</span>
        </div>
        <Timeline load={() => fetchOpportunityTimeline(opp.id)} version={version} />
      </div>

      {lostOpen && (
        <LostReasonModal
          dealName={opp.name}
          onClose={() => setLostOpen(false)}
          onConfirm={async (reason) => {
            await updateOpportunity(opp.id, { stage: "Lost", lost_reason: reason });
            setLostOpen(false);
            await refresh();
          }}
        />
      )}
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
