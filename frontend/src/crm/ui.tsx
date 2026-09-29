import { useEffect, useState, type ReactNode } from "react";
import { Icon } from "../components/Icon";
import { relativeDue } from "../lib/format";
import type { Assignee, DuplicateMatch } from "../api/client";

function useEscape(onClose: () => void) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
}

export function Modal({
  title,
  onClose,
  children,
  footer,
  wide = false,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  wide?: boolean;
}) {
  useEscape(onClose);
  return (
    <div className="overlay center" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`modal${wide ? " wide" : ""}`} role="dialog" aria-modal="true" aria-label={title}>
        <div className="modal-head">
          <h2>{title}</h2>
          <button className="icon-btn" onClick={onClose} aria-label="Close">
            <Icon name="x" />
          </button>
        </div>
        <div className="modal-body">{children}</div>
        {footer && <div className="modal-foot">{footer}</div>}
      </div>
    </div>
  );
}

export function Drawer({
  title,
  subtitle,
  onClose,
  children,
}: {
  title: string;
  subtitle?: ReactNode;
  onClose: () => void;
  children: ReactNode;
}) {
  useEscape(onClose);
  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <aside className="drawer" role="dialog" aria-modal="true" aria-label={title}>
        <div className="drawer-head">
          <div>
            <h2>{title}</h2>
            {subtitle && <p>{subtitle}</p>}
          </div>
          <button className="icon-btn" onClick={onClose} aria-label="Close">
            <Icon name="x" />
          </button>
        </div>
        <div className="drawer-body">{children}</div>
      </aside>
    </div>
  );
}

/** Owner picker. Read-only (disabled) without the record's assign permission (crm.lead.assign / crm.opportunity.assign). */
export function OwnerPicker({
  value,
  assignees,
  onChange,
  canAssign,
  label = "Owner",
}: {
  value: string | null;
  assignees: Assignee[];
  onChange: (ownerId: string | null) => void;
  canAssign: boolean;
  label?: string;
}) {
  return (
    <select
      className={`select-sm${value ? "" : " unassigned"}`}
      value={value ?? ""}
      disabled={!canAssign}
      title={canAssign ? label : "You don't have permission to reassign this"}
      aria-label={label}
      onClick={(e) => e.stopPropagation()}
      onChange={(e) => onChange(e.target.value || null)}
    >
      <option value="">Unassigned</option>
      {assignees.map((a) => (
        <option key={a.id} value={a.id}>
          {a.display_name}
        </option>
      ))}
    </select>
  );
}

/** The overdue-activity indicator used on every lead / opportunity row and card. */
export function FollowUpBadge({
  overdue,
  open,
  nextDueAt,
}: {
  overdue: number;
  open: number;
  nextDueAt: string | null;
}) {
  if (overdue > 0) {
    return (
      <span className="followup overdue" title={`${overdue} of ${open} open follow-ups are past due`}>
        <Icon name="alert" size={14} />
        {overdue} overdue
      </span>
    );
  }
  if (open > 0 && nextDueAt) {
    return (
      <span className="followup">
        <Icon name="clock" size={14} />
        {relativeDue(nextDueAt)}
      </span>
    );
  }
  return <span className="followup none">No follow-up</span>;
}

/** An open deal nobody has touched for longer than its stage allows. */
export function IdleBadge({ days }: { days: number }) {
  return (
    <span className="followup idle" title="No stage change, follow-up or quotation recently — this deal is going cold">
      <Icon name="clock" size={14} />
      Idle {days} day{days === 1 ? "" : "s"}
    </span>
  );
}

export function ErrorNote({ message }: { message: string | null }) {
  if (!message) return null;
  return <div className="notice bad">{message}</div>;
}

/** "51–100 of 1,240" with previous/next buttons; hidden when everything fits on one page. */
export function Pager({
  page,
  pageSize,
  total,
  onPage,
}: {
  page: number;
  pageSize: number;
  total: number;
  onPage: (page: number) => void;
}) {
  if (total <= pageSize) return null;
  const last = Math.ceil(total / pageSize) - 1;
  return (
    <div className="pager">
      <span>
        {(page * pageSize + 1).toLocaleString("en-IN")}–{Math.min(total, (page + 1) * pageSize).toLocaleString("en-IN")} of{" "}
        {total.toLocaleString("en-IN")}
      </span>
      <button className="ghost-btn sm" disabled={page === 0} onClick={() => onPage(page - 1)}>
        Previous
      </button>
      <button className="ghost-btn sm" disabled={page >= last} onClick={() => onPage(page + 1)}>
        Next
      </button>
    </div>
  );
}

/** A search box that waits for a pause in typing before searching. */
export function SearchBox({
  value,
  onChange,
  placeholder,
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
}) {
  const [text, setText] = useState(value);
  useEffect(() => setText(value), [value]);
  useEffect(() => {
    if (text === value) return;
    const t = window.setTimeout(() => onChange(text.trim()), 300);
    return () => window.clearTimeout(t);
  }, [text, value, onChange]);
  return (
    <label className="search-box">
      <Icon name="search" size={16} />
      <input type="search" value={text} onChange={(e) => setText(e.target.value)} placeholder={placeholder} aria-label={placeholder} />
    </label>
  );
}

/** Shown when the server finds a likely duplicate: link to the match or create anyway. */
export function DuplicateWarning({
  noun,
  matches,
  busy,
  onCreate,
  onBack,
  onUse,
}: {
  noun: string;
  matches: DuplicateMatch[];
  busy: boolean;
  onCreate: () => void;
  onBack: () => void;
  /** Offer "Use this one" per match (e.g. pick the existing customer instead). */
  onUse?: (id: string) => void;
}) {
  return (
    <div className="notice warn dup-warning" role="alert">
      <b>Possible duplicate — {matches.length === 1 ? `a ${noun} like this already exists` : `${matches.length} ${noun}s like this already exist`}:</b>
      <ul>
        {matches.map((m) => (
          <li key={m.id}>
            {m.label}
            {m.detail && <small> · {m.detail}</small>}
            {onUse && (
              <button type="button" className="link-btn" onClick={() => onUse(m.id)}>
                Use this one
              </button>
            )}
          </li>
        ))}
      </ul>
      <div className="form-actions">
        <button type="button" className="secondary-btn" onClick={onBack}>
          Go back
        </button>
        <button type="button" className="primary-btn" disabled={busy} onClick={onCreate}>
          {busy ? "Saving…" : `Create anyway`}
        </button>
      </div>
    </div>
  );
}
