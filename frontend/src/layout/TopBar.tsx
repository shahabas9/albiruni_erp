import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  ApiError,
  fetchNotificationPreferences,
  fetchNotifications,
  markNotificationsRead,
  saveNotificationPreferences,
  type AppNotification,
  type NotificationPreferences,
} from "../api/client";
import { Icon, type IconName } from "../components/Icon";
import { ErrorNote, Modal } from "../crm/ui";
import { useLanguage } from "../i18n/LanguageProvider";
import { useAskErp } from "../askerp/AskErpContext";
import { useAuth } from "../auth/AuthProvider";
import { useAppData } from "../data/AppDataProvider";
import { useTheme } from "../theme/ThemeProvider";
import { useSpeech } from "../lib/useSpeech";
import { initials } from "../lib/format";

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

const KIND_ICON: Record<string, IconName> = {
  lead_assigned: "user",
  deal_assigned: "target",
  followup_assigned: "calendar",
  followup_overdue: "alert",
  web_enquiry: "send",
  import: "file",
  invoice_overdue: "wallet",
};

function Notifications() {
  const [open, setOpen] = useState(false);
  const ref = useOutsideClose(() => setOpen(false));
  const { quotes, crm, version } = useAppData();
  const navigate = useNavigate();
  const [items, setItems] = useState<AppNotification[]>([]);
  const [unread, setUnread] = useState(0);
  const pending = quotes.filter((q) => q.status === "Pending approval");
  const overdueCount = crm?.overdue_followups ?? 0;

  const load = useCallback(async () => {
    try {
      const r = await fetchNotifications();
      setItems(r.items);
      setUnread(r.unread);
    } catch {
      // the bell stays as it was; the next poll tries again
    }
  }, []);

  // New notifications arrive from other people's actions and the background worker, so poll.
  useEffect(() => {
    void load();
    const t = window.setInterval(() => void load(), 60_000);
    return () => window.clearInterval(t);
  }, [load, version]);

  async function openItem(n: AppNotification) {
    setOpen(false);
    if (!n.read_at) {
      setItems((all) => all.map((x) => (x.id === n.id ? { ...x, read_at: new Date().toISOString() } : x)));
      setUnread((u) => Math.max(0, u - 1));
      void markNotificationsRead([n.id]);
    }
    if (n.link) navigate(n.link);
  }

  async function readAll() {
    await markNotificationsRead();
    await load();
  }

  const badge = unread + pending.length;

  return (
    <div className="user-menu" ref={ref}>
      <button
        className="icon-btn"
        onClick={() => setOpen((v) => !v)}
        aria-label={unread ? `Notifications, ${unread} unread` : "Notifications"}
        aria-expanded={open}
      >
        <Icon name="bell" size={22} />
        {badge > 0 && <span className="bell-count">{badge > 99 ? "99+" : badge}</span>}
      </button>
      {open && (
        <div className="menu-pop notif-list">
          <div className="notif-head">
            <b>Notifications</b>
            {unread > 0 && (
              <button className="link-btn" onClick={readAll}>
                Mark all read
              </button>
            )}
          </div>
          {pending.length > 0 && (
            <button onClick={() => (setOpen(false), navigate("/sales?status=pending"))}>
              <Icon name="file" size={16} />
              {pending.length} quotation{pending.length === 1 ? "" : "s"} awaiting approval
            </button>
          )}
          {overdueCount > 0 && (
            <button onClick={() => (setOpen(false), navigate("/activities?show=overdue"))}>
              <Icon name="alert" size={16} />
              <span style={{ color: "var(--bad)" }}>
                {overdueCount} follow-up{overdueCount === 1 ? "" : "s"} overdue now
              </span>
            </button>
          )}
          {items.length === 0 && pending.length === 0 && overdueCount === 0 && (
            <div className="empty">Nothing needs you right now.</div>
          )}
          {items.map((n) => (
            <button key={n.id} className={n.read_at ? "read" : "unread"} onClick={() => openItem(n)}>
              <Icon name={KIND_ICON[n.kind] ?? "bell"} size={16} />
              <span>
                <b>{n.title}</b>
                {n.body && (
                  <>
                    <br />
                    <small>{n.body}</small>
                  </>
                )}
                <br />
                <small className="notif-time">{relativeTime(n.created_at)}</small>
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function relativeTime(iso: string) {
  const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours} h ago`;
  return new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short" });
}

/** Where your notifications are emailed. */
function NotificationSettings({ onClose }: { onClose: () => void }) {
  const [prefs, setPrefs] = useState<NotificationPreferences | null>(null);
  const [email, setEmail] = useState("");
  const [on, setOn] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    fetchNotificationPreferences()
      .then((p) => {
        setPrefs(p);
        setEmail(p.email);
        setOn(p.notify_email);
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : "Couldn't load your settings."));
  }, []);

  async function save() {
    setSaving(true);
    setError(null);
    try {
      await saveNotificationPreferences({ email: email.trim(), notify_email: on });
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't save.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal
      title="Notifications"
      onClose={onClose}
      footer={
        <>
          <button className="ghost-btn" onClick={onClose}>
            Cancel
          </button>
          <button className="primary-btn" disabled={!prefs || saving} onClick={save}>
            {saving ? "Saving…" : "Save"}
          </button>
        </>
      }
    >
      <p className="card-note" style={{ marginTop: 0 }}>
        You're told in the bell when a lead, deal or follow-up is given to you, when a follow-up goes overdue, and about
        web enquiries. Add an email to get them there too.
      </p>
      {prefs && !prefs.email_enabled && (
        <div className="notice warn">Email isn't set up on this server yet, so for now they appear in the bell only.</div>
      )}
      <label className="field">
        <span>Email</span>
        <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@company.com" />
      </label>
      <label className="toggle-row" style={{ marginTop: 12 }}>
        <input type="checkbox" checked={on} onChange={(e) => setOn(e.target.checked)} />
        <span>Email me my notifications</span>
      </label>
      <ErrorNote message={error} />
    </Modal>
  );
}

function UserMenu() {
  const [open, setOpen] = useState(false);
  const ref = useOutsideClose(() => setOpen(false));
  const { user, logout } = useAuth();
  const { resolved, toggle } = useTheme();
  const [settingsOpen, setSettingsOpen] = useState(false);

  return (
    <div className="user-menu" ref={ref}>
      {settingsOpen && <NotificationSettings onClose={() => setSettingsOpen(false)} />}
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
          <button onClick={() => (setOpen(false), setSettingsOpen(true))}>
            <Icon name="bell" size={16} /> Notification settings
          </button>
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
