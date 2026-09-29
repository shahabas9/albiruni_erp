import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  ApiError,
  OPPORTUNITY_STAGES,
  assignOpportunity,
  createOpportunity,
  fetchCustomers,
  updateOpportunity,
  type Customer,
  type Opportunity,
  type OpportunityStage,
} from "../api/client";
import { CustomerPicker } from "../components/CustomerPicker";
import { useAuth } from "../auth/AuthProvider";
import { useOpenOpportunity } from "../crm/drawerHost";
import { FollowUpBadge, IdleBadge, OwnerPicker } from "../crm/ui";
import { useAppData } from "../data/AppDataProvider";

type OwnerFilter = "all" | "mine" | "unassigned";

function formatInr(n: number): string {
  return `₹${n.toLocaleString("en-IN")}`;
}

export function Opportunities() {
  const [customers, setCustomers] = useState<Customer[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [params] = useSearchParams();
  const [showForm, setShowForm] = useState(params.get("new") === "1");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [stageFilter, setStageFilter] = useState<"all" | OpportunityStage>("all");
  const [owner, setOwner] = useState<OwnerFilter>("all");
  const { user } = useAuth();
  const { opportunities, loading, error: loadError, assignees, refresh: reload, can } = useAppData();
  const openOpp = useOpenOpportunity();

  async function assign(o: Opportunity, ownerId: string | null) {
    try {
      await assignOpportunity(o.id, ownerId);
      await reload();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't reassign.");
    }
  }

  // The customer picker needs the customer list; only the create/edit form uses it.
  useEffect(() => {
    if (!can("sales.customer.read")) {
      setCustomers([]);
      return;
    }
    fetchCustomers()
      .then(setCustomers)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Couldn't load customers."));
  }, [can]);

  const openStages = OPPORTUNITY_STAGES.filter((s) => s !== "Won" && s !== "Lost");
  const stageTotals = useMemo(() => {
    const totals = new Map<string, number>();
    for (const o of opportunities) totals.set(o.stage, (totals.get(o.stage) ?? 0) + o.value);
    return totals;
  }, [opportunities]);

  const byStage = stageFilter === "all" ? opportunities : opportunities.filter((o) => o.stage === stageFilter);
  const visible =
    owner === "mine"
      ? byStage.filter((o) => o.owner_user_id === user?.id)
      : owner === "unassigned"
        ? byStage.filter((o) => !o.owner_user_id)
        : byStage;

  return (
    <section>
      <div className="page-head">
        <div className="eyebrow">CRM</div>
        <h1 className="page-title">Opportunities</h1>
        <p className="page-sub">Quantified deals against a customer, moving toward Won or Lost. Open a deal to change its stage, schedule follow-ups or raise a quotation.</p>
      </div>

      {(error ?? loadError) && <div className="error-banner">{error ?? loadError}</div>}

      {opportunities.length > 0 && (
        <div className="grid brief" style={{ marginBottom: 18 }}>
          {openStages.map((stage) => (
            <div className="card brief-card" key={stage}>
              <h3>
                <span>{stage}</span>
              </h3>
              <div className="hl-num mono" style={{ fontSize: 22 }}>
                {formatInr(stageTotals.get(stage) ?? 0)}
              </div>
              <p style={{ margin: "4px 0 0", fontSize: 12, color: "var(--ink-dim)" }}>
                {opportunities.filter((o) => o.stage === stage).length} open
              </p>
            </div>
          ))}
        </div>
      )}

      <div className="toolbar">
        <div className="filters">
          <button className={stageFilter === "all" ? "on" : ""} onClick={() => setStageFilter("all")}>
            All ({opportunities.length})
          </button>
          {OPPORTUNITY_STAGES.map((s) => (
            <button key={s} className={stageFilter === s ? "on" : ""} onClick={() => setStageFilter(s)}>
              {s} ({opportunities.filter((o) => o.stage === s).length})
            </button>
          ))}
        </div>
        <div className="filters" aria-label="Owner filter">
          {(["all", "mine", "unassigned"] as const).map((f) => (
            <button key={f} className={owner === f ? "on" : ""} onClick={() => setOwner(f)}>
              {f === "all" ? "Everyone" : f === "mine" ? "Mine" : "Unassigned"}
            </button>
          ))}
        </div>
        {can("crm.opportunity.write") && (
          <button className="primary-btn" onClick={() => setShowForm((v) => !v)}>
            {showForm ? "Cancel" : "+ New opportunity"}
          </button>
        )}
      </div>

      {showForm && customers && (
        <OpportunityForm
          customers={customers}
          ownerId={user?.id ?? null}
          onCustomerCreated={(c) => setCustomers((prev) => [...(prev ?? []), c])}
          onDone={() => {
            setShowForm(false);
            reload();
          }}
        />
      )}

      {!loading && opportunities.length === 0 && !showForm && (
        <div className="card" style={{ textAlign: "center", color: "var(--ink-dim)" }}>
          No opportunities yet.
        </div>
      )}

      {visible.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Deal</th>
                <th>Stage</th>
                <th>Value</th>
                <th>Close</th>
                <th>Owner</th>
                <th>Next follow-up</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {visible.map((o) =>
                editingId === o.id && customers ? (
                  <tr key={o.id}>
                    <td colSpan={8}>
                      <OpportunityForm
                        customers={customers}
                        opportunity={o}
                        onDone={() => {
                          setEditingId(null);
                          reload();
                        }}
                      />
                    </td>
                  </tr>
                ) : (
                  <tr key={o.id}>
                    <td style={{ whiteSpace: "normal", minWidth: 180 }}>
                      <button
                        className="link-btn"
                        style={{ padding: 0, textAlign: "left" }}
                        onClick={() => openOpp(o.id)}
                        title="Open deal — stage, follow-ups and quotations"
                      >
                        {o.name}
                      </button>
                      <span className="sub">
                        {o.customer_name}
                        {o.quotations.length ? ` · ${o.quotations.length} quote${o.quotations.length === 1 ? "" : "s"}` : ""}
                      </span>
                    </td>
                    <td>
                      <span className={`badge ${o.stage === "Won" ? "status-confirmed" : o.stage === "Lost" ? "status-draft" : "status-pending"}`}>
                        {o.stage}
                      </span>
                    </td>
                    <td>
                      <span className="num">{formatInr(o.value)}</span>
                      <span className="sub">{o.probability_pct}% likely</span>
                    </td>
                    <td>{o.expected_close_date ?? "—"}</td>
                    <td>
                      <OwnerPicker value={o.owner_user_id} assignees={assignees} canAssign={can("crm.opportunity.assign")} onChange={(id) => assign(o, id)} />
                    </td>
                    <td>
                      {o.is_stale ? (
                        <IdleBadge days={o.idle_days} />
                      ) : (
                        <FollowUpBadge overdue={o.overdue_activities} open={o.open_activities} nextDueAt={o.next_due_at} />
                      )}
                    </td>
                    <td style={{ display: "flex", gap: 6, justifyContent: "flex-end" }}>
                      {can("crm.opportunity.write") && customers && (
                        <button className="ghost-btn sm" onClick={() => setEditingId(o.id)}>
                          Edit
                        </button>
                      )}
                    </td>
                  </tr>
                ),
              )}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

/** New opportunities are owned by whoever creates them; reassign from the Owner column. */
function OpportunityForm({
  customers,
  opportunity,
  ownerId,
  onCustomerCreated,
  onDone,
}: {
  customers: Customer[];
  opportunity?: Opportunity;
  ownerId?: string | null;
  onCustomerCreated?: (customer: Customer) => void;
  onDone: () => void;
}) {
  const [localCustomers, setLocalCustomers] = useState(customers);
  const [customerId, setCustomerId] = useState(opportunity?.customer_id ?? customers[0]?.id ?? "");
  const [name, setName] = useState(opportunity?.name ?? "");
  const [stage, setStage] = useState<OpportunityStage>(opportunity?.stage ?? "New");
  const [value, setValue] = useState(String(opportunity?.value ?? 0));
  const [probability, setProbability] = useState(String(opportunity?.probability_pct ?? 50));
  const [closeDate, setCloseDate] = useState(opportunity?.expected_close_date ?? "");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function save() {
    setSaving(true);
    setError(null);
    try {
      if (opportunity) {
        await updateOpportunity(opportunity.id, {
          name,
          stage,
          value: Number(value),
          probability_pct: Number(probability),
          expected_close_date: closeDate || null,
        });
      } else {
        await createOpportunity({
          customer_id: customerId,
          name,
          value: Number(value),
          probability_pct: Number(probability),
          expected_close_date: closeDate || null,
          owner_user_id: ownerId ?? null,
        });
      }
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
        {!opportunity && (
          <CustomerPicker
            customers={localCustomers}
            value={customerId}
            onChange={setCustomerId}
            onCustomerCreated={(c) => {
              setLocalCustomers((prev) => [...prev, c]);
              onCustomerCreated?.(c);
            }}
          />
        )}
        <label className="field">
          <span>Opportunity name</span>
          <input value={name} onChange={(e) => setName(e.target.value)} autoFocus placeholder="e.g. Q4 bulk order" />
        </label>
        {opportunity && (
          <label className="field">
            <span>Stage</span>
            <select value={stage} onChange={(e) => setStage(e.target.value as OpportunityStage)}>
              {OPPORTUNITY_STAGES.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </label>
        )}
        <label className="field">
          <span>Value (₹)</span>
          <input type="number" min={0} value={value} onChange={(e) => setValue(e.target.value)} />
        </label>
        <label className="field">
          <span>Probability (%)</span>
          <input type="number" min={0} max={100} value={probability} onChange={(e) => setProbability(e.target.value)} />
        </label>
        <label className="field">
          <span>Expected close date</span>
          <input type="date" value={closeDate} onChange={(e) => setCloseDate(e.target.value)} />
        </label>
      </div>
      {error && <div className="error-banner">{error}</div>}
      <div className="form-actions">
        <button className="primary-btn" disabled={!name.trim() || !customerId || saving} onClick={save}>
          {saving ? "Saving…" : "Save"}
        </button>
        <button className="secondary-btn" onClick={onDone}>
          Cancel
        </button>
      </div>
    </div>
  );
}
