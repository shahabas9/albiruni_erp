import { useCallback, useState } from "react";
import { inr, currencyLabel } from "../lib/format";
import { Link, useSearchParams } from "react-router-dom";
import {
  ApiError,
  OPPORTUNITY_STAGES,
  assignOpportunity,
  bulkAction,
  createOpportunity,
  fetchOpportunities,
  updateOpportunity,
  type CustomValues,
  type Opportunity,
  type OpportunityStage,
} from "../api/client";
import { CustomerPicker } from "../components/CustomerPicker";
import { SavedViews } from "../components/SavedViews";
import { recallFilters } from "../lib/filterMemory";
import { ExportButton } from "../components/ExportButton";
import { useAuth } from "../auth/AuthProvider";
import { useOpenOpportunity } from "../crm/drawerHost";
import { BulkBar, useSelection, type BulkActionDef } from "../crm/BulkBar";
import { CustomFieldInputs, TagChips, TagFilter, TagInput, changedCustom, useCustomFields } from "../crm/fields";
import { FollowUpBadge, IdleBadge, OwnerPicker, Pager, SearchBox, ownerParam, type OwnerFilter } from "../crm/ui";
import { useAppData } from "../data/AppDataProvider";
import { PAGE_SIZE, usePaged } from "../lib/usePaged";

function formatInr(n: number): string {
  return `${inr(n)}`;
}

export function Opportunities() {
  const [error, setError] = useState<string | null>(null);
  const [params] = useSearchParams();
  const [showForm, setShowForm] = useState(params.get("new") === "1");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [saved] = useState(() =>
    ["stale", "stage", "tag"].some((k) => params.has(k)) ? {} : recallFilters("opportunities"),
  );
  const [stageFilter, setStageFilter] = useState<"all" | "stale" | OpportunityStage>(() => {
    if (params.get("stale") === "1") return "stale";
    const stage = (params.get("stage") ?? saved.stage) as OpportunityStage | "stale" | null;
    return stage === "stale" ? "stale" : stage && OPPORTUNITY_STAGES.includes(stage) ? stage : "all";
  });
  const [owner, setOwner] = useState<OwnerFilter>((saved.owner as OwnerFilter) || "all");
  const [search, setSearch] = useState(String(saved.search ?? ""));
  const [tag, setTag] = useState(params.get("tag") ?? String(saved.tag ?? ""));
  const onSearch = useCallback((q: string) => setSearch(q), []);
  const { user } = useAuth();
  const { crm, version, assignees, refresh: reload, can } = useAppData();
  const openOpp = useOpenOpportunity();
  const list = usePaged(
    (limit, offset) =>
      fetchOpportunities({
        q: search,
        stage: stageFilter === "all" || stageFilter === "stale" ? "" : stageFilter,
        stale: stageFilter === "stale",
        owner: ownerParam(owner),
        tag,
        limit,
        offset,
      }),
    `${search}|${stageFilter}|${owner}|${tag}`,
    version,
  );
  const visible = list.rows;
  const sel = useSelection(visible.map((o) => o.id), `${search}|${stageFilter}|${owner}|${tag}|${list.page}`);
  const bulkEnabled = can("crm.opportunity.write") || can("crm.opportunity.assign") || can("crm.opportunity.delete");
  const bulkActions: BulkActionDef[] = [
    ...(can("crm.opportunity.assign") ? [{ key: "assign", label: "Assign to", input: "owner" as const }] : []),
    ...(can("crm.opportunity.write")
      ? [
          { key: "add_tag", label: "Add tag", input: "tag" as const },
          { key: "remove_tag", label: "Remove tag", input: "tag" as const },
          { key: "stage", label: "Move to stage", input: "choice" as const, options: OPPORTUNITY_STAGES },
        ]
      : []),
    ...(can("crm.opportunity.delete") ? [{ key: "delete", label: "Delete", input: "none" as const, danger: true }] : []),
  ];
  const stageCount = (s: OpportunityStage) =>
    s === "Won" ? crm?.won_deals : s === "Lost" ? crm?.lost_deals : crm?.by_stage.find((b) => b.stage === s)?.count;

  async function assign(o: Opportunity, ownerId: string | null) {
    try {
      await assignOpportunity(o.id, ownerId);
      await reload();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't reassign.");
    }
  }



  return (
    <section>
      <div className="page-head">
        <div className="eyebrow">CRM</div>
        <h1 className="page-title">Opportunities</h1>
        <p className="page-sub">Quantified deals against a customer, moving toward Won or Lost. Open a deal to change its stage, schedule follow-ups or raise a quotation.</p>
      </div>

      {(error ?? list.error) && <div className="error-banner">{error ?? list.error}</div>}

      {crm && crm.open_deals > 0 && (
        <div className="grid brief" style={{ marginBottom: 18 }}>
          {crm.by_stage.map(({ stage, count, value }) => (
            <div className="card brief-card" key={stage}>
              <h3>
                <span>{stage}</span>
              </h3>
              <div className="hl-num mono" style={{ fontSize: 22 }}>
                {formatInr(value)}
              </div>
              <p style={{ margin: "4px 0 0", fontSize: 12, color: "var(--ink-dim)" }}>{count} open</p>
            </div>
          ))}
        </div>
      )}

      <div className="toolbar">
        <div className="filters">
          <button className={stageFilter === "all" ? "on" : ""} onClick={() => setStageFilter("all")}>
            All
          </button>
          {OPPORTUNITY_STAGES.map((s) => (
            <button key={s} className={stageFilter === s ? "on" : ""} onClick={() => setStageFilter(s)}>
              {s}
              {stageCount(s) !== undefined && ` (${stageCount(s)})`}
            </button>
          ))}
          <button className={stageFilter === "stale" ? "on" : ""} onClick={() => setStageFilter("stale")}>
            Going stale{crm ? ` (${crm.stale_deals})` : ""}
          </button>
        </div>
        <div className="filters" aria-label="Owner filter">
          {(["all", "mine", "unassigned"] as const).map((f) => (
            <button key={f} className={owner === f ? "on" : ""} onClick={() => setOwner(f)}>
              {f === "all" ? "Everyone" : f === "mine" ? "Mine" : "Unassigned"}
            </button>
          ))}
        </div>
        <SavedViews
          page="opportunities"
          filters={{ stage: stageFilter, owner, tag, search }}
          onApply={(f) => {
            const stage = String(f.stage ?? "all");
            setStageFilter(stage === "stale" || OPPORTUNITY_STAGES.includes(stage as OpportunityStage) ? (stage as OpportunityStage) : "all");
            setOwner(((f.owner as OwnerFilter) || "all") as OwnerFilter);
            setTag(String(f.tag ?? ""));
            setSearch(String(f.search ?? ""));
          }}
        />
        <TagFilter recordType="opportunity" value={tag} onChange={setTag} version={version} />
        <SearchBox value={search} onChange={onSearch} placeholder="Search deal or customer" />
        <ExportButton
          kind="opportunities"
          filters={{
            q: search,
            stage: stageFilter === "all" || stageFilter === "stale" ? "" : stageFilter,
            stale: stageFilter === "stale" || undefined,
            owner: ownerParam(owner),
            tag,
          }}
          onError={setError}
        />
        {can("crm.opportunity.write") && (
          <button className="primary-btn" onClick={() => setShowForm((v) => !v)}>
            {showForm ? "Cancel" : "+ New opportunity"}
          </button>
        )}
      </div>

      {showForm && (
        <OpportunityForm
          ownerId={user?.id ?? null}
          onDone={() => {
            setShowForm(false);
            reload();
          }}
        />
      )}

      {bulkEnabled && (
        <BulkBar
          selection={sel}
          total={list.total}
          noun="deal"
          actions={bulkActions}
          assignees={assignees}
          run={(action, value, lostReason, target) =>
            bulkAction("opportunities", {
              action,
              value,
              lost_reason: lostReason,
              ...(target.all
                ? {
                    filters: {
                    q: search,
                    stage: stageFilter === "all" || stageFilter === "stale" ? "" : stageFilter,
                    stale: stageFilter === "stale" || undefined,
                    owner: ownerParam(owner),
                    tag,
                  },
                  }
                : { ids: target.ids }),
            })
          }
          onDone={() => void reload()}
        />
      )}

      {!list.loading && list.total === 0 && !showForm && (
        <div className="card" style={{ textAlign: "center", color: "var(--ink-dim)" }}>
          {search || tag || stageFilter !== "all" || owner !== "all" ? "No opportunities match this filter." : "No opportunities yet."}
        </div>
      )}

      {visible.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                {bulkEnabled && (
                  <th className="check-col">
                    <input type="checkbox" aria-label="Select all on this page" checked={sel.allOnPage} onChange={sel.togglePage} />
                  </th>
                )}
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
                editingId === o.id ? (
                  <tr key={o.id}>
                    <td colSpan={bulkEnabled ? 9 : 8}>
                      <OpportunityForm
                        opportunity={o}
                        onDone={() => {
                          setEditingId(null);
                          reload();
                        }}
                      />
                    </td>
                  </tr>
                ) : (
                  <tr key={o.id} className={sel.has(o.id) ? "selected" : undefined}>
                    {bulkEnabled && (
                      <td className="check-col">
                        <input type="checkbox" aria-label={`Select ${o.name}`} checked={sel.has(o.id)} onChange={() => sel.toggle(o.id)} />
                      </td>
                    )}
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
                        <Link to={`/customers/${o.customer_id}`}>{o.customer_name}</Link>
                        {o.quotations.length ? ` · ${o.quotations.length} quote${o.quotations.length === 1 ? "" : "s"}` : ""}
                      </span>
                      <TagChips tags={o.tags} onClick={setTag} />
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
                      {can("crm.opportunity.write") && (
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
      <Pager page={list.page} pageSize={PAGE_SIZE} total={list.total} onPage={list.setPage} />
    </section>
  );
}

/** New opportunities are owned by whoever creates them; reassign from the Owner column. */
function OpportunityForm({
  opportunity,
  ownerId,
  onDone,
}: {
  opportunity?: Opportunity;
  ownerId?: string | null;
  onDone: () => void;
}) {
  const [customerId, setCustomerId] = useState(opportunity?.customer_id ?? "");
  const [name, setName] = useState(opportunity?.name ?? "");
  const [stage, setStage] = useState<OpportunityStage>(opportunity?.stage ?? "New");
  const [value, setValue] = useState(String(opportunity?.value ?? 0));
  const [probability, setProbability] = useState(String(opportunity?.probability_pct ?? 50));
  const [closeDate, setCloseDate] = useState(opportunity?.expected_close_date ?? "");
  const [tags, setTags] = useState<string[]>(opportunity?.tags ?? []);
  const customFields = useCustomFields("opportunity");
  const [custom, setCustom] = useState<CustomValues>(opportunity?.custom ?? {});
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
          tags,
          custom: changedCustom(opportunity.custom, custom),
        });
      } else {
        await createOpportunity({
          customer_id: customerId,
          name,
          value: Number(value),
          probability_pct: Number(probability),
          expected_close_date: closeDate || null,
          owner_user_id: ownerId ?? null,
          tags,
          custom,
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
          <CustomerPicker value={customerId} onChange={setCustomerId} />
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
          <span>Value ({currencyLabel()})</span>
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
        <CustomFieldInputs fields={customFields} values={custom} onChange={setCustom} />
        <div className="field full">
          <span>Tags</span>
          <TagInput value={tags} onChange={setTags} recordType="opportunity" />
        </div>
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
