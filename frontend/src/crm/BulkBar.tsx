import { useEffect, useState } from "react";
import { ApiError, LOST_REASONS, type Assignee, type BulkResult } from "../api/client";
import { ErrorNote } from "./ui";

export interface BulkActionDef {
  key: string;
  label: string;
  /** What the action needs: an owner, a tag, a choice from `options`, or nothing. */
  input: "owner" | "tag" | "choice" | "none";
  options?: string[];
  danger?: boolean;
}

/** Row selection for a paged list: ids on this page, or everything matching the filters. */
export function useSelection(pageIds: string[], resetKey: string) {
  const [ids, setIds] = useState<Set<string>>(new Set());
  const [allMatching, setAllMatching] = useState(false);
  useEffect(() => {
    setIds(new Set());
    setAllMatching(false);
  }, [resetKey]);
  const allOnPage = pageIds.length > 0 && pageIds.every((id) => ids.has(id));
  return {
    ids,
    allMatching,
    setAllMatching,
    has: (id: string) => allMatching || ids.has(id),
    toggle: (id: string) => {
      setAllMatching(false);
      setIds((prev) => {
        const next = new Set(prev);
        if (next.has(id)) next.delete(id);
        else next.add(id);
        return next;
      });
    },
    allOnPage: allOnPage || (allMatching && pageIds.length > 0),
    togglePage: () => {
      setAllMatching(false);
      setIds((prev) => {
        const next = new Set(prev);
        if (allOnPage) pageIds.forEach((id) => next.delete(id));
        else pageIds.forEach((id) => next.add(id));
        return next;
      });
    },
    clear: () => {
      setIds(new Set());
      setAllMatching(false);
    },
  };
}

export function BulkBar({
  selection,
  total,
  noun,
  actions,
  assignees,
  run,
  onDone,
}: {
  selection: ReturnType<typeof useSelection>;
  total: number;
  noun: string;
  actions: BulkActionDef[];
  assignees: Assignee[];
  run: (action: string, value: string | null, lostReason: string, target: { ids?: string[]; all?: true }) => Promise<BulkResult>;
  onDone: () => void;
}) {
  const [action, setAction] = useState(actions[0]?.key ?? "");
  const [value, setValue] = useState("");
  const [lostReason, setLostReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<BulkResult | null>(null);
  const count = selection.allMatching ? total : selection.ids.size;
  if (count === 0 && !result) return null;

  const def = actions.find((a) => a.key === action);
  const needsValue = def?.input === "tag" || def?.input === "choice";
  const needsLost = action === "stage" && value === "Lost";
  const ready = def && (!needsValue || value.trim()) && (!needsLost || lostReason.trim());

  async function apply() {
    if (!def) return;
    const what = `${def.label.toLowerCase()} for ${count} ${noun}${count === 1 ? "" : "s"}`;
    if (def.danger && !window.confirm(`Really ${what}? This can't be undone.`)) return;
    setBusy(true);
    setError(null);
    try {
      const target = selection.allMatching ? { all: true as const } : { ids: [...selection.ids] };
      const r = await run(action, def.input === "none" ? null : value || null, lostReason, target);
      setResult(r);
      selection.clear();
      onDone();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't apply that.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="bulk-bar" role="region" aria-label="Bulk actions">
      {count > 0 && (
        <div className="bulk-row">
          <b>
            {count} {noun}
            {count === 1 ? "" : "s"} selected
          </b>
          {!selection.allMatching && selection.ids.size > 0 && total > selection.ids.size && (
            <button className="link-btn" onClick={() => selection.setAllMatching(true)}>
              Select all {total} matching
            </button>
          )}
          <button className="link-btn" onClick={selection.clear}>
            Clear
          </button>
          <select value={action} onChange={(e) => (setAction(e.target.value), setValue(""))} aria-label="Bulk action">
            {actions.map((a) => (
              <option key={a.key} value={a.key}>
                {a.label}
              </option>
            ))}
          </select>
          {def?.input === "owner" && (
            <select value={value} onChange={(e) => setValue(e.target.value)} aria-label="New owner">
              <option value="">Unassigned</option>
              {assignees.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.display_name}
                </option>
              ))}
            </select>
          )}
          {def?.input === "tag" && <input value={value} onChange={(e) => setValue(e.target.value)} placeholder="Tag" aria-label="Tag" />}
          {def?.input === "choice" && (
            <select value={value} onChange={(e) => setValue(e.target.value)} aria-label="New value">
              <option value="">Choose…</option>
              {def.options?.map((o) => (
                <option key={o} value={o}>
                  {o}
                </option>
              ))}
            </select>
          )}
          {needsLost && (
            <select value={lostReason} onChange={(e) => setLostReason(e.target.value)} aria-label="Lost reason">
              <option value="">Why lost?</option>
              {LOST_REASONS.map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </select>
          )}
          <button className={def?.danger ? "danger-btn" : "primary-btn sm"} disabled={!ready || busy} onClick={apply}>
            {busy ? "Working…" : "Apply"}
          </button>
        </div>
      )}
      <ErrorNote message={error} />
      {result && (
        <div className={`notice ${result.skipped.length ? "warn" : "good"}`}>
          Done for {result.done} of {result.matched}.
          {result.skipped.length > 0 && (
            <>
              {" "}
              Skipped {result.skipped.length}:
              <ul>
                {result.skipped.slice(0, 8).map((s) => (
                  <li key={s.id}>
                    {s.label} — {s.reason}
                  </li>
                ))}
              </ul>
            </>
          )}
          <button className="link-btn" onClick={() => setResult(null)}>
            Dismiss
          </button>
        </div>
      )}
    </div>
  );
}
