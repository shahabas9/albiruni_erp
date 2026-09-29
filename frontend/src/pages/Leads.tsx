import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  ApiError,
  LEAD_STATUSES,
  assignLead,
  convertLead,
  createLead,
  fetchLeadCustomerMatches,
  fetchLeadTimeline,
  fetchLeads,
  updateLead,
  type CustomerMatch,
  type DuplicateMatch,
  type Lead,
  type LeadStatus,
} from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import { CsvImport } from "../components/CsvImport";
import { Icon } from "../components/Icon";
import { useOpenOpportunity } from "../crm/drawerHost";
import { ContactActions } from "../crm/ContactActions";
import { FollowUpModal } from "../crm/forms";
import { Timeline } from "../crm/Timeline";
import { Drawer, DuplicateWarning, FollowUpBadge, Modal, OwnerPicker, Pager, SearchBox, ownerParam, type OwnerFilter } from "../crm/ui";
import { useAppData } from "../data/AppDataProvider";
import { PAGE_SIZE, usePaged } from "../lib/usePaged";

function statusClass(status: LeadStatus) {
  if (status === "Converted") return "status-confirmed";
  if (status === "Lost") return "status-draft";
  if (status === "Qualified") return "status-pending";
  return "status-draft";
}

export function Leads() {
  const [error, setError] = useState<string | null>(null);
  const [params] = useSearchParams();
  const [showForm, setShowForm] = useState(params.get("new") === "1");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [converting, setConverting] = useState<Lead | null>(null);
  const [followUpFor, setFollowUpFor] = useState<Lead | null>(null);
  const [importing, setImporting] = useState(false);
  const [historyFor, setHistoryFor] = useState<Lead | null>(null);
  const [owner, setOwner] = useState<OwnerFilter>((params.get("owner") as OwnerFilter) || "all");
  const [status, setStatus] = useState(params.get("status") ?? "");
  const [search, setSearch] = useState("");
  const onSearch = useCallback((q: string) => setSearch(q), []);
  const { user } = useAuth();
  const { version, assignees, refresh: reload, can } = useAppData();
  const openOpp = useOpenOpportunity();
  // "Unassigned" means open leads nobody owns; converted/lost ones don't need an owner.
  const statusParam = owner === "unassigned" && !status ? "open" : status;
  const list = usePaged(
    (limit, offset) =>
      fetchLeads({ q: search, status: statusParam, owner: ownerParam(owner), limit, offset }),
    `${search}|${statusParam}|${owner}`,
    version,
  );
  const visible = list.rows;
  const filtered = Boolean(search || status || owner !== "all");

  async function assign(lead: Lead, ownerId: string | null) {
    try {
      await assignLead(lead.id, ownerId);
      await reload();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't reassign.");
    }
  }


  return (
    <section>
      <div className="page-head">
        <div className="eyebrow">CRM</div>
        <h1 className="page-title">Leads</h1>
        <p className="page-sub">Raw, unqualified interest. Give every lead an owner and a next step; convert a qualified one into a Customer, Contact and Opportunity in one step.</p>
      </div>

      {(error ?? list.error) && <div className="error-banner">{error ?? list.error}</div>}

      <div className="toolbar">
        <div className="filters" aria-label="Owner filter">
          {(["all", "mine", "unassigned"] as const).map((f) => (
            <button key={f} className={owner === f ? "on" : ""} onClick={() => setOwner(f)}>
              {f === "all" ? "Everyone" : f === "mine" ? "Mine" : "Unassigned"}
            </button>
          ))}
        </div>
        <select className="filter-select" value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Status filter">
          <option value="">All statuses</option>
          <option value="open">Open (not converted or lost)</option>
          {LEAD_STATUSES.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
        <SearchBox value={search} onChange={onSearch} placeholder="Search name, company, phone, email" />
        {can("crm.lead.write") && (
          <div style={{ display: "flex", gap: 8 }}>
            <button className="ghost-btn" onClick={() => setImporting(true)}>
              Import CSV
            </button>
            <button className="primary-btn" onClick={() => setShowForm((v) => !v)}>
              {showForm ? "Cancel" : "+ New lead"}
            </button>
          </div>
        )}
        {importing && <CsvImport kind="leads" onClose={() => setImporting(false)} onImported={reload} />}
      </div>

      {showForm && <LeadForm ownerId={user?.id ?? null} onDone={() => { setShowForm(false); reload(); }} />}

      {!list.loading && list.total === 0 && !showForm && (
        <div className="card" style={{ textAlign: "center", color: "var(--ink-dim)" }}>
          {filtered ? "No leads match this filter." : "No leads yet — add one above."}
        </div>
      )}

      {visible.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Lead</th>
                <th>Status</th>
                <th>Owner</th>
                <th>Next follow-up</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {visible.map((l) =>
                editingId === l.id ? (
                  <tr key={l.id}>
                    <td colSpan={5}>
                      <LeadForm lead={l} onDone={() => { setEditingId(null); reload(); }} />
                    </td>
                  </tr>
                ) : (
                  <tr key={l.id}>
                    <td>
                      <div className="cell-with-actions">
                        <div>
                          <b>{l.company_name || l.name}</b>
                          <span className="sub">
                            {[l.company_name ? l.name : "", l.source].filter(Boolean).join(" · ") || "—"}
                          </span>
                        </div>
                        {l.status !== "Converted" && (
                          <ContactActions phone={l.phone} name={l.name} target={{ lead_id: l.id }} onLogged={reload} />
                        )}
                      </div>
                    </td>
                    <td>
                      <span className={`badge ${statusClass(l.status)}`}>{l.status}</span>
                    </td>
                    <td>
                      <OwnerPicker
                        value={l.owner_user_id}
                        assignees={assignees}
                        canAssign={can("crm.lead.assign") && l.status !== "Converted"}
                        onChange={(id) => assign(l, id)}
                      />
                    </td>
                    <td>
                      {l.status === "Converted" ? (
                        "—"
                      ) : (
                        <FollowUpBadge overdue={l.overdue_activities} open={l.open_activities} nextDueAt={l.next_due_at} />
                      )}
                    </td>
                    <td style={{ display: "flex", gap: 6, justifyContent: "flex-end" }}>
                      <button className="ghost-btn sm" onClick={() => setHistoryFor(l)} title="History" aria-label="History">
                        <Icon name="clock" size={14} />
                      </button>
                      {l.status === "Converted" && l.converted_opportunity_id && (
                        <button className="ghost-btn sm" onClick={() => openOpp(l.converted_opportunity_id!)}>
                          Open deal
                        </button>
                      )}
                      {l.status !== "Converted" && (
                        <>
                          {can("crm.lead.write") && (
                            <button className="ghost-btn sm" onClick={() => setEditingId(l.id)}>
                              Edit
                            </button>
                          )}
                          {can("crm.activity.write") && (
                            <button className="ghost-btn sm" onClick={() => setFollowUpFor(l)}>
                              Follow-up
                            </button>
                          )}
                          {can("crm.lead.convert") && (
                            <button
                              className="primary-btn sm"
                              disabled={l.status === "Lost"}
                              title={l.status === "Lost" ? "Re-qualify this lead before converting" : undefined}
                              onClick={() => setConverting(l)}
                            >
                              Convert
                            </button>
                          )}
                        </>
                      )}
                    </td>
                  </tr>
                ),
              )}
            </tbody>
          </table>
        </div>
      )}
      <Pager page={list.page} pageSize={PAGE_SIZE} total={list.total} onPage={list.setPage} />

      {converting && (
        <Modal title={`Convert ${converting.company_name || converting.name}`} onClose={() => setConverting(null)} wide>
          <ConvertForm
            lead={converting}
            onDone={async (opportunityId) => {
              setConverting(null);
              await reload();
              if (opportunityId) openOpp(opportunityId);
            }}
            onCancel={() => setConverting(null)}
          />
        </Modal>
      )}

      {historyFor && (
        <Drawer
          title={historyFor.company_name || historyFor.name}
          subtitle={`History · ${historyFor.status}`}
          onClose={() => setHistoryFor(null)}
        >
          <Timeline load={() => fetchLeadTimeline(historyFor.id)} version={version} />
        </Drawer>
      )}

      {followUpFor && (
        <FollowUpModal
          target={{ lead_id: followUpFor.id, name: followUpFor.company_name || followUpFor.name }}
          onClose={() => setFollowUpFor(null)}
          onSaved={async () => {
            setFollowUpFor(null);
            await reload();
          }}
        />
      )}
    </section>
  );
}

/** New leads are owned by whoever creates them; reassign from the Owner column. */
function LeadForm({ lead, ownerId, onDone }: { lead?: Lead; ownerId?: string | null; onDone: () => void }) {
  const [name, setName] = useState(lead?.name ?? "");
  const [companyName, setCompanyName] = useState(lead?.company_name ?? "");
  const [email, setEmail] = useState(lead?.email ?? "");
  const [phone, setPhone] = useState(lead?.phone ?? "");
  const [source, setSource] = useState(lead?.source ?? "");
  const [status, setStatus] = useState<LeadStatus>(lead?.status ?? "New");
  const [error, setError] = useState<string | null>(null);
  const [duplicates, setDuplicates] = useState<DuplicateMatch[] | null>(null);
  const [saving, setSaving] = useState(false);

  async function save(allowDuplicate = false) {
    setSaving(true);
    setError(null);
    try {
      if (lead) {
        await updateLead(lead.id, { name, company_name: companyName, email, phone, source, status });
      } else {
        await createLead({
          name,
          company_name: companyName,
          email,
          phone,
          source,
          owner_user_id: ownerId ?? null,
          allow_duplicate: allowDuplicate,
        });
      }
      onDone();
    } catch (err) {
      if (err instanceof ApiError && err.duplicates) setDuplicates(err.duplicates);
      else setError(err instanceof ApiError ? err.message : "Couldn't save.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="card form-card">
      <div className="field-grid">
        <label className="field">
          <span>Name</span>
          <input value={name} onChange={(e) => setName(e.target.value)} autoFocus />
        </label>
        <label className="field">
          <span>Company</span>
          <input value={companyName} onChange={(e) => setCompanyName(e.target.value)} />
        </label>
        <label className="field">
          <span>Email</span>
          <input type="email" value={email} onChange={(e) => (setEmail(e.target.value), setDuplicates(null))} />
        </label>
        <label className="field">
          <span>Phone</span>
          <input value={phone} onChange={(e) => (setPhone(e.target.value), setDuplicates(null))} />
        </label>
        <label className="field">
          <span>Source</span>
          <input value={source} onChange={(e) => setSource(e.target.value)} placeholder="e.g. Referral, Website" />
        </label>
        {lead && (
          <label className="field">
            <span>Status</span>
            <select value={status} onChange={(e) => setStatus(e.target.value as LeadStatus)}>
              {LEAD_STATUSES.filter((s) => s !== "Converted").map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>
      {error && <div className="error-banner">{error}</div>}
      {duplicates && (
        <DuplicateWarning
          noun="lead"
          matches={duplicates}
          busy={saving}
          onCreate={() => save(true)}
          onBack={() => setDuplicates(null)}
        />
      )}
      <div className="form-actions" hidden={Boolean(duplicates)}>
        <button className="primary-btn" disabled={!name.trim() || saving} onClick={() => save()}>
          {saving ? "Saving…" : "Save"}
        </button>
        <button className="secondary-btn" onClick={onDone}>
          Cancel
        </button>
      </div>
    </div>
  );
}

function ConvertForm({
  lead,
  onDone,
  onCancel,
}: {
  lead: Lead;
  onDone: (opportunityId: string | null) => void;
  onCancel: () => void;
}) {
  const [createOpportunity, setCreateOpportunity] = useState(true);
  const [value, setValue] = useState("0");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [matches, setMatches] = useState<CustomerMatch[] | null>(null);
  // "new" = create a customer; otherwise an existing customer's id. Unset until
  // the user chooses when there are look-alikes — never guessed.
  const [customerChoice, setCustomerChoice] = useState<string | null>(null);
  const newName = lead.company_name || lead.name;

  useEffect(() => {
    fetchLeadCustomerMatches(lead.id)
      .then((found) => {
        setMatches(found);
        if (found.length === 0) setCustomerChoice("new");
      })
      .catch(() => {
        setMatches([]);
        setCustomerChoice("new");
      });
  }, [lead.id]);

  async function save() {
    setSaving(true);
    setError(null);
    try {
      const result = await convertLead(lead.id, {
        customer_id: customerChoice === "new" ? null : customerChoice,
        create_opportunity: createOpportunity,
        opportunity_value: Number(value),
      });
      onDone(result.opportunity_id);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't convert.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="convert-form">
      <p style={{ margin: 0, fontSize: 13, color: "var(--ink-dim)" }}>
        Converts <b style={{ color: "var(--ink)" }}>{lead.name}</b> into a Contact on a Customer.
      </p>
      {matches === null ? (
        <p className="card-note">Checking for existing customers…</p>
      ) : (
        <fieldset className="choice-list">
          {matches.length > 0 && (
            <legend>
              {matches.length === 1 ? "An existing customer looks like this lead" : `${matches.length} existing customers look like this lead`} — is it one of them?
            </legend>
          )}
          {matches.map((m) => (
            <label key={m.id} className={customerChoice === m.id ? "on" : ""}>
              <input type="radio" name={`customer-${lead.id}`} checked={customerChoice === m.id} onChange={() => setCustomerChoice(m.id)} />
              <span>
                <b>Add to {m.name}</b>
                <small>{[m.gstin, ...m.reasons].filter(Boolean).join(" · ")}</small>
              </span>
            </label>
          ))}
          <label className={customerChoice === "new" ? "on" : ""}>
            <input type="radio" name={`customer-${lead.id}`} checked={customerChoice === "new"} onChange={() => setCustomerChoice("new")} />
            <span>
              <b>Create a new customer “{newName}”</b>
              {matches.length > 0 && <small>A different business that happens to share the name or number</small>}
            </span>
          </label>
        </fieldset>
      )}
      <label className="field" style={{ flexDirection: "row", alignItems: "center", gap: 8, justifyContent: "flex-start" }}>
        <input type="checkbox" checked={createOpportunity} onChange={(e) => setCreateOpportunity(e.target.checked)} />
        <span>Also open an Opportunity</span>
      </label>
      {createOpportunity && (
        <label className="field" style={{ maxWidth: 220 }}>
          <span>Estimated value (₹)</span>
          <input type="number" min={0} value={value} onChange={(e) => setValue(e.target.value)} />
        </label>
      )}
      {error && <div className="error-banner">{error}</div>}
      <div className="form-actions">
        <button className="primary-btn" disabled={saving || !customerChoice} onClick={save}>
          {saving ? "Converting…" : customerChoice ? "Confirm conversion" : "Choose a customer above"}
        </button>
        <button className="secondary-btn" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </div>
  );
}
