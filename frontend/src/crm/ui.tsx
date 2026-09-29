import { useEffect, type ReactNode } from "react";
import { Icon } from "../components/Icon";
import { relativeDue } from "../lib/format";
import type { Assignee } from "../api/client";

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
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
}) {
  useEscape(onClose);
  return (
    <div className="overlay center" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal" role="dialog" aria-modal="true" aria-label={title}>
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
