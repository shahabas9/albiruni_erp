import { useEffect, useMemo, useState } from "react";
import {
  ApiError,
  OPPORTUNITY_STAGES,
  createOpportunity,
  fetchCustomers,
  fetchOpportunities,
  updateOpportunity,
  type Customer,
  type Opportunity,
  type OpportunityStage,
} from "../api/client";
import { CustomerPicker } from "../components/CustomerPicker";

function formatInr(n: number): string {
  return `₹${n.toLocaleString("en-IN")}`;
}

export function Opportunities() {
  const [opportunities, setOpportunities] = useState<Opportunity[]>([]);
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [stageFilter, setStageFilter] = useState<"all" | OpportunityStage>("all");

  async function refresh() {
    setLoading(true);
    try {
      const [o, c] = await Promise.all([fetchOpportunities(), fetchCustomers()]);
      setOpportunities(o);
      setCustomers(c);
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't reach the Albiruni API.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  const openStages = OPPORTUNITY_STAGES.filter((s) => s !== "Won" && s !== "Lost");
  const stageTotals = useMemo(() => {
    const totals = new Map<string, number>();
    for (const o of opportunities) totals.set(o.stage, (totals.get(o.stage) ?? 0) + o.value);
    return totals;
  }, [opportunities]);

  const visible = stageFilter === "all" ? opportunities : opportunities.filter((o) => o.stage === stageFilter);

  return (
    <section>
      <div className="page-head">
        <div className="eyebrow">CRM</div>
        <h1 className="page-title">Opportunities</h1>
        <p className="page-sub">The pipeline — quantified deals in progress against a customer, moving through stages toward Won or Lost.</p>
      </div>

      {error && <div className="error-banner">{error}</div>}

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
        <button className="primary-btn" onClick={() => setShowForm((v) => !v)}>
          {showForm ? "Cancel" : "+ New opportunity"}
        </button>
      </div>

      {showForm && (
        <OpportunityForm
          customers={customers}
          onCustomerCreated={(c) => setCustomers((prev) => [...prev, c])}
          onDone={() => {
            setShowForm(false);
            refresh();
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
                <th>Name</th>
                <th>Customer</th>
                <th>Stage</th>
                <th>Value</th>
                <th>Probability</th>
                <th>Expected close</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {visible.map((o) =>
                editingId === o.id ? (
                  <tr key={o.id}>
                    <td colSpan={7}>
                      <OpportunityForm
                        customers={customers}
                        opportunity={o}
                        onDone={() => {
                          setEditingId(null);
                          refresh();
                        }}
                      />
                    </td>
                  </tr>
                ) : (
                  <tr key={o.id}>
                    <td>{o.name}</td>
                    <td>{o.customer_name}</td>
                    <td>
                      <span className={`badge ${o.stage === "Won" ? "status-confirmed" : o.stage === "Lost" ? "status-draft" : "status-pending"}`}>
                        {o.stage}
                      </span>
                    </td>
                    <td className="mono">{formatInr(o.value)}</td>
                    <td className="mono">{o.probability_pct}%</td>
                    <td>{o.expected_close_date ?? "—"}</td>
                    <td>
                      <button className="secondary-btn" onClick={() => setEditingId(o.id)}>
                        Edit
                      </button>
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

function OpportunityForm({
  customers,
  opportunity,
  onCustomerCreated,
  onDone,
}: {
  customers: Customer[];
  opportunity?: Opportunity;
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
