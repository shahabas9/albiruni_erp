import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  ApiError,
  deleteCustomer,
  fetchActivities,
  fetchContacts,
  fetchCustomerOverview,
  fetchCustomerTimeline,
  fetchOpportunities,
  fetchQuotations,
  updateActivity,
  type Activity,
  type Contact,
  type CustomerOverview,
  type Opportunity,
  type Quotation,
} from "../api/client";
import { Icon } from "../components/Icon";
import { Attachments } from "../crm/Attachments";
import { ContactActions } from "../crm/ContactActions";
import { useOpenOpportunity } from "../crm/drawerHost";
import { CustomFieldValues, TagChips, useCustomFields } from "../crm/fields";
import { FollowUpModal } from "../crm/forms";
import { Timeline } from "../crm/Timeline";
import { ErrorNote } from "../crm/ui";
import { useAppData } from "../data/AppDataProvider";
import { dateTime, dayDate, inr, inrShort, quoteStatusClass, relativeDue, taxLabel } from "../lib/format";
import { CustomerForm } from "./Customers";

/** Everything about one customer on one page. */
export function CustomerPage() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const openOpp = useOpenOpportunity();
  const { can, version, refresh: refreshShared } = useAppData();
  const fields = useCustomFields("customer");
  const [overview, setOverview] = useState<CustomerOverview | null>(null);
  const [deals, setDeals] = useState<Opportunity[]>([]);
  const [quotes, setQuotes] = useState<Quotation[]>([]);
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [followUps, setFollowUps] = useState<Activity[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [followUpOpen, setFollowUpOpen] = useState(false);
  const [changes, setChanges] = useState(0);

  const load = useCallback(async () => {
    const optional = <T,>(ok: boolean, p: () => Promise<T>, empty: T) => (ok ? p() : Promise.resolve(empty));
    try {
      const [o, d, q, c, a] = await Promise.all([
        fetchCustomerOverview(id),
        optional(can("crm.opportunity.read"), () => fetchOpportunities({ customer_id: id, limit: 100 }), { rows: [], total: 0 }),
        optional(can("sales.quotation.read"), () => fetchQuotations(id), [] as Quotation[]),
        optional(can("crm.contact.read"), () => fetchContacts({ customer_id: id, limit: 100 }), { rows: [], total: 0 }),
        optional(can("crm.activity.read"), () => fetchActivities({ customer_id: id, show: "open", limit: 50 }), {
          rows: [],
          total: 0,
        }),
      ]);
      setOverview(o);
      setDeals(d.rows);
      setQuotes(q);
      setContacts(c.rows);
      setFollowUps(a.rows);
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't load this customer.");
    }
  }, [id, can]);

  useEffect(() => {
    void load();
  }, [load, version, changes]);

  const changed = () => setChanges((n) => n + 1);

  if (!overview) {
    return (
      <section>
        <Link to="/customers" className="back-link">
          ← Customers
        </Link>
        <ErrorNote message={error} />
        {!error && <p className="card-note">Loading…</p>}
      </section>
    );
  }

  const c = overview.customer;
  const open = deals.filter((d) => !["Won", "Lost"].includes(d.stage));
  const closed = deals.filter((d) => ["Won", "Lost"].includes(d.stage));

  async function remove() {
    if (!window.confirm(`Delete ${c.name}? Its contacts, notes and files go too. This can't be undone.`)) return;
    try {
      await deleteCustomer(c.id);
      navigate("/customers");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't delete.");
    }
  }

  return (
    <section className="customer-page">
      <Link to="/customers" className="back-link">
        ← Customers
      </Link>
      <div className="page-head">
        <div>
          <h1 className="page-title">{c.name}</h1>
          <p className="page-sub">
            <span className={`badge ${c.active ? "status-confirmed" : "status-draft"}`}>{c.active ? "Active" : "Inactive"}</span>{" "}
            {c.vat_number ? <span className="mono">VAT {c.vat_number}</span> : c.gstin ? <span className="mono">GSTIN {c.gstin}</span> : `Unregistered for ${taxLabel()}`} · Credit limit {inr(c.credit_limit)}
            {c.state_code ? ` · State ${c.state_code}` : ""}
            {c.payment_terms_days != null ? ` · Pays in ${c.payment_terms_days} days` : ""}
          </p>
          {c.billing_address && <p className="page-sub" style={{ whiteSpace: "pre-line" }}>{c.billing_address}</p>}
          <TagChips tags={c.tags} />
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {can("crm.activity.write") && (
            <button className="ghost-btn" onClick={() => setFollowUpOpen(true)}>
              <Icon name="plus" size={16} /> Follow-up
            </button>
          )}
          {can("sales.customer.write") && (
            <button className="primary-btn" onClick={() => setEditing((v) => !v)}>
              {editing ? "Cancel" : "Edit"}
            </button>
          )}
        </div>
      </div>

      <ErrorNote message={error} />
      {editing && (
        <CustomerForm
          customer={c}
          onDone={() => {
            setEditing(false);
            changed();
          }}
        />
      )}

      <div className="forecast-strip">
        <Stat label="Open pipeline" value={inrShort(overview.open_value)} sub={`${overview.open_deals} open deal${overview.open_deals === 1 ? "" : "s"}`} />
        <Stat label="Won" value={inrShort(overview.won_value)} sub={`${overview.won_deals} won · ${overview.lost_deals} lost`} />
        <Stat
          label="Quoted"
          value={overview.quoted_value === null ? "—" : inrShort(overview.quoted_value)}
          sub={overview.quotations === null ? "No access to quotations" : `${overview.quotations} quotation${overview.quotations === 1 ? "" : "s"}`}
        />
        <Stat label="People" value={String(overview.contacts)} sub="Contacts at this customer" />
      </div>

      <div className="customer-grid">
        <div>
          {can("crm.opportunity.read") && (
            <div className="card">
              <div className="card-head">
                <span className="card-title">Deals</span>
                <span className="card-note">{open.length} open</span>
              </div>
              {deals.length === 0 && <p className="card-note" style={{ margin: 0 }}>No deals yet.</p>}
              <div className="mini-list">
                {[...open, ...closed].map((d) => (
                  <div className="row" key={d.id}>
                    <span className={`badge ${d.stage === "Won" ? "good" : d.stage === "Lost" ? "bad" : "accent"}`}>{d.stage}</span>
                    <div className="grow">
                      <button className="link-btn" style={{ padding: 0, textAlign: "left" }} onClick={() => openOpp(d.id)}>
                        {d.name}
                      </button>
                      <small>
                        {d.owner_name ?? "Unassigned"}
                        {d.stage === "Lost" && d.lost_reason ? ` · ${d.lost_reason}` : ""}
                      </small>
                    </div>
                    <b className="num">{inrShort(d.value)}</b>
                  </div>
                ))}
              </div>
            </div>
          )}

          {can("sales.quotation.read") && (
            <div className="card">
              <div className="card-head">
                <span className="card-title">Quotations</span>
              </div>
              {quotes.length === 0 && <p className="card-note" style={{ margin: 0 }}>No quotations yet.</p>}
              <div className="mini-list">
                {quotes.slice(0, 20).map((q) => (
                  <div className="row" key={q.id}>
                    <Icon name="file" size={18} />
                    <div className="grow">
                      <b className="mono">{q.number}</b>
                      <small>
                        {dateTime(q.created_at)}
                        {q.opportunity_title ? ` · ${q.opportunity_title}` : ""}
                      </small>
                    </div>
                    <span className={`badge ${quoteStatusClass(q.status)}`}>{q.status}</span>
                    <b className="num">{inr(q.total)}</b>
                  </div>
                ))}
              </div>
            </div>
          )}

          {can("crm.activity.read") && (
            <div className="card">
              <div className="card-head">
                <span className="card-title">Open follow-ups on the account</span>
              </div>
              {followUps.length === 0 && (
                <p className="card-note" style={{ margin: 0 }}>
                  None. Follow-ups on this customer's deals show in each deal.
                </p>
              )}
              <div className="mini-list">
                {followUps.map((a) => (
                  <div className={`row${a.is_overdue ? " overdue" : ""}`} key={a.id}>
                    <Icon name="calendar" size={18} />
                    <div className="grow">
                      {a.subject}
                      <small>
                        {a.type}
                        {a.due_at ? ` · ${relativeDue(a.due_at)}` : ""}
                        {a.owner_name ? ` · ${a.owner_name}` : ""}
                      </small>
                    </div>
                    {can("crm.activity.write") && (
                      <button
                        className="ghost-btn sm"
                        onClick={async () => {
                          await updateActivity(a.id, { done: true });
                          changed();
                          void refreshShared();
                        }}
                      >
                        Done
                      </button>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {can("crm.contact.read") && (
            <div className="card">
              <div className="card-head">
                <span className="card-title">People</span>
                <Link className="link-btn" to="/contacts">
                  Manage contacts
                </Link>
              </div>
              {contacts.length === 0 && <p className="card-note" style={{ margin: 0 }}>No contacts yet.</p>}
              <div className="mini-list">
                {contacts.map((p) => (
                  <div className="row" key={p.id}>
                    <Icon name="user" size={18} />
                    <div className="grow">
                      {p.name}
                      <small>{[p.title, p.phone, p.email].filter(Boolean).join(" · ") || "No phone or email"}</small>
                    </div>
                    <ContactActions phone={p.phone} name={p.name} target={{ customer_id: c.id }} onLogged={changed} />
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        <div>
          {overview.account && (overview.account.owed > 0 || overview.account.advance > 0 || overview.account.open_invoices > 0) && (
            <div className="card account-card">
              <div className="card-head">
                <span className="card-title">Account</span>
                <Link className="link-btn" to={`/sales/receivables/${c.id}`}>
                  Statement
                </Link>
              </div>
              <div className="row">
                <span>Owed on {overview.account.open_invoices} invoice{overview.account.open_invoices === 1 ? "" : "s"}</span>
                <b className="num">{inr(overview.account.owed)}</b>
              </div>
              {overview.account.overdue > 0 && (
                <div className="row">
                  <span>Overdue{overview.account.oldest_due ? ` (since ${dayDate(overview.account.oldest_due)})` : ""}</span>
                  <b className="num qty-out">{inr(overview.account.overdue)}</b>
                </div>
              )}
              {overview.account.advance > 0 && (
                <div className="row">
                  <span>Advance held</span>
                  <b className="num">{inr(overview.account.advance)}</b>
                </div>
              )}
              {overview.account.credit_limit > 0 && (
                <div className="row">
                  <span>Credit limit</span>
                  <span className="num">{inr(overview.account.credit_limit)}</span>
                </div>
              )}
            </div>
          )}
          {fields.length > 0 && (
            <div className="card">
              <div className="card-head">
                <span className="card-title">Details</span>
              </div>
              <CustomFieldValues fields={fields} values={c.custom} />
              {!fields.some((f) => c.custom[f.key] != null) && <p className="card-note" style={{ margin: 0 }}>Nothing filled in yet.</p>}
            </div>
          )}
          <div className="card">
            <div className="card-head">
              <span className="card-title">Files</span>
            </div>
            <Attachments recordType="customer" recordId={c.id} canWrite={can("sales.customer.write")} onChange={changed} />
          </div>
          <div className="card">
            <div className="card-head">
              <span className="card-title">History</span>
            </div>
            <Timeline load={() => fetchCustomerTimeline(c.id)} version={version + changes} />
          </div>
          {can("sales.customer.delete") && (
            <div className="danger-zone">
              <button className="danger-btn" onClick={remove}>
                Delete customer
              </button>
            </div>
          )}
        </div>
      </div>

      {followUpOpen && (
        <FollowUpModal
          target={{ customer_id: c.id, name: c.name }}
          onClose={() => setFollowUpOpen(false)}
          onSaved={() => {
            setFollowUpOpen(false);
            changed();
            void refreshShared();
          }}
        />
      )}
    </section>
  );
}

function Stat({ label, value, sub }: { label: string; value: string; sub: string }) {
  return (
    <div className="card stat">
      <div className="stat-label">{label}</div>
      <div className="stat-value num">{value}</div>
      <div className="stat-sub">{sub}</div>
    </div>
  );
}
