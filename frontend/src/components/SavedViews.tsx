import { useEffect, useRef, useState } from "react";
import { ApiError, createView, deleteView, fetchViews, type SavedView, type ViewFilters, type ViewPage } from "../api/client";
import { rememberFilters } from "../lib/filterMemory";
import { Icon } from "./Icon";

function same(a: ViewFilters, b: ViewFilters) {
  const keys = new Set([...Object.keys(a), ...Object.keys(b)]);
  return [...keys].every((k) => (a[k] ?? "") === (b[k] ?? ""));
}

/** Saved filter sets for a list page, plus remembering the current filters in this browser. */
export function SavedViews({
  page,
  filters,
  onApply,
}: {
  page: ViewPage;
  filters: ViewFilters;
  onApply: (filters: ViewFilters) => void;
}) {
  const [views, setViews] = useState<SavedView[]>([]);
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [name, setName] = useState("");
  const [shared, setShared] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const ref = useRef<HTMLDivElement>(null);

  // Remember whatever is on screen, so the page reopens the same way.
  const serialized = JSON.stringify(filters);
  useEffect(() => {
    rememberFilters(page, JSON.parse(serialized) as ViewFilters);
  }, [page, serialized]);

  async function load() {
    try {
      setViews(await fetchViews(page));
    } catch {
      setViews([]);
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page]);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false);
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const current = views.find((v) => same(v.filters, filters));

  async function save() {
    setError(null);
    try {
      await createView({ page, name: name.trim(), filters, shared });
      setSaving(false);
      setOpen(false);
      setName("");
      setShared(false);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't save the view.");
    }
  }

  async function remove(v: SavedView) {
    if (!window.confirm(`Delete the view “${v.name}”?`)) return;
    try {
      await deleteView(v.id);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't delete the view.");
    }
  }

  return (
    <div className="views-menu" ref={ref}>
      <button className="ghost-btn" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        {current ? current.name : "Views"} <Icon name="down" size={14} />
      </button>
      {open && (
        <div className="menu-pop views-pop">
          {views.length === 0 && <div className="empty">No saved views yet.</div>}
          {views.map((v) => (
            <div className="view-row" key={v.id}>
              <button
                className={current?.id === v.id ? "on" : ""}
                onClick={() => {
                  onApply(v.filters);
                  setOpen(false);
                }}
              >
                <b>{v.name}</b>
                {v.shared && <small>{v.mine ? "Shared by you" : `Shared by ${v.owner_name ?? "a colleague"}`}</small>}
              </button>
              {v.mine && (
                <button className="icon-btn sm" aria-label={`Delete view ${v.name}`} onClick={() => remove(v)}>
                  <Icon name="x" size={14} />
                </button>
              )}
            </div>
          ))}
          <div className="views-save">
            {saving ? (
              <>
                <input autoFocus value={name} maxLength={60} placeholder="Name this view" onChange={(e) => setName(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && name.trim() && save()} />
                <label className="toggle-row">
                  <input type="checkbox" checked={shared} onChange={(e) => setShared(e.target.checked)} />
                  <span>Share with the team</span>
                </label>
                <div style={{ display: "flex", gap: 6 }}>
                  <button className="primary-btn sm" disabled={!name.trim()} onClick={save}>
                    Save
                  </button>
                  <button className="ghost-btn sm" onClick={() => setSaving(false)}>
                    Cancel
                  </button>
                </div>
              </>
            ) : (
              <button className="link-btn" disabled={Boolean(current)} onClick={() => setSaving(true)}>
                {current ? "This is a saved view" : "+ Save current filters as a view"}
              </button>
            )}
            {error && <div className="error-banner">{error}</div>}
          </div>
        </div>
      )}
    </div>
  );
}
