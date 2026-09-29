import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Icon } from "../components/Icon";
import { useLanguage } from "../i18n/LanguageProvider";
import { useAskErp } from "../askerp/AskErpContext";
import { useAuth } from "../auth/AuthProvider";
import { useAppData } from "../data/AppDataProvider";
import { useTheme } from "../theme/ThemeProvider";
import { useSpeech } from "../lib/useSpeech";
import { initials, relativeDue } from "../lib/format";

function useOutsideClose(onClose: () => void) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose();
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [onClose]);
  return ref;
}

export function TopBar({ onMenu }: { onMenu: () => void }) {
  const { lang } = useLanguage();
  const { ask } = useAskErp();
  const [query, setQuery] = useState("");
  const speech = useSpeech(lang === "ml" ? "ml-IN" : "en-IN", (text) => ask(text));

  const submit = () => {
    const text = query.trim();
    if (!text) return;
    setQuery("");
    ask(text);
  };

  return (
    <header className="topbar">
      <button className="icon-btn menu-btn" onClick={onMenu} aria-label="Open navigation">
        <Icon name="menu" />
      </button>
      <form
        className="omnibox"
        role="search"
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        <Icon name="search" />
        <input
          value={speech.listening ? speech.interim || "Listening…" : query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search or ask anything…"
          aria-label="Search or ask Ask ERP"
          readOnly={speech.listening}
        />
        <button
          type="button"
          className={`icon-btn${speech.listening ? " listening" : ""}`}
          onClick={speech.toggle}
          disabled={!speech.supported}
          title={speech.supported ? "Ask by voice" : "Voice input isn't supported in this browser"}
          aria-label="Ask by voice"
        >
          <Icon name="mic" />
        </button>
      </form>
      <div className="topbar-right">
        <CompanyChip />
        <Notifications />
        <UserMenu />
      </div>
    </header>
  );
}

function CompanyChip() {
  const { user } = useAuth();
  // One company per login today; this becomes a branch switcher once the
  // backend scopes a user to several companies.
  return (
    <span className="chip-btn" style={{ cursor: "default" }} title="Your company">
      <Icon name="building" size={18} />
      <span className="chip-label">{user?.company ?? "—"}</span>
    </span>
  );
}

function Notifications() {
  const [open, setOpen] = useState(false);
  const ref = useOutsideClose(() => setOpen(false));
  const { activities, quotes } = useAppData();
  const navigate = useNavigate();
  const overdue = activities.filter((a) => a.is_overdue);
  const pending = quotes.filter((q) => q.status === "Pending approval");
  const hasAny = overdue.length + pending.length > 0;

  const go = (to: string) => {
    setOpen(false);
    navigate(to);
  };

  return (
    <div className="user-menu" ref={ref}>
      <button className="icon-btn" onClick={() => setOpen((v) => !v)} aria-label="Notifications" aria-expanded={open}>
        <Icon name="bell" size={22} />
        {hasAny && <span className="ping" />}
      </button>
      {open && (
        <div className="menu-pop notif-list">
          {!hasAny && <div className="empty">Nothing needs you right now.</div>}
          {overdue.slice(0, 5).map((a) => (
            <button key={a.id} onClick={() => go(a.opportunity_id ? `/crm?opp=${a.opportunity_id}` : "/crm?tab=followups")}>
              <Icon name="alert" size={16} />
              <span>
                <b>{a.subject}</b>
                <br />
                <small style={{ color: "var(--bad)" }}>
                  {a.related_name} · {relativeDue(a.due_at)}
                </small>
              </span>
            </button>
          ))}
          {pending.length > 0 && (
            <button onClick={() => go("/sales?status=pending")}>
              <Icon name="file" size={16} />
              {pending.length} quotation{pending.length === 1 ? "" : "s"} awaiting approval
            </button>
          )}
        </div>
      )}
    </div>
  );
}

function UserMenu() {
  const [open, setOpen] = useState(false);
  const ref = useOutsideClose(() => setOpen(false));
  const { user, logout } = useAuth();
  const { resolved, toggle } = useTheme();

  return (
    <div className="user-menu" ref={ref}>
      <button className="user-btn" onClick={() => setOpen((v) => !v)} aria-expanded={open} aria-label="Account menu">
        <span className="avatar">{initials(user?.display_name)}</span>
        <span className="user-name">{user?.display_name}</span>
        <Icon name="down" size={16} />
      </button>
      {open && (
        <div className="menu-pop">
          <div className="who">
            <b>{user?.display_name}</b>
            <small>
              {user?.role ?? "No role"} · {user?.company}
            </small>
          </div>
          <button onClick={toggle}>
            <Icon name={resolved === "dark" ? "sun" : "moon"} size={16} />
            {resolved === "dark" ? "Day mode" : "Night mode"}
          </button>
          <button onClick={logout}>
            <Icon name="logout" size={16} /> Sign out
          </button>
        </div>
      )}
    </div>
  );
}
