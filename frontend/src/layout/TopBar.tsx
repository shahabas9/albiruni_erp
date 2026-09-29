import { NavLink } from "react-router-dom";
import { ThemeToggle } from "../components/ThemeToggle";
import { useLanguage } from "../i18n/LanguageProvider";
import { useAskErp } from "../askerp/AskErpContext";
import { useAuth } from "../auth/AuthProvider";
import type { Lang } from "../i18n/strings";

export function TopBar() {
  const { t, lang, setLang } = useLanguage();
  const { open } = useAskErp();
  const { user, logout } = useAuth();

  return (
    <header className="topbar">
      <div className="topbar-left">
        <span className="brand">
          <span className="mark">A</span> Albiruni <span style={{ opacity: 0.55, fontWeight: 400 }}>ERP</span>
        </span>
        <nav className="tabs">
          <NavLink to="/" end className={({ isActive }) => (isActive ? "active" : "")}>
            {t("nav.dashboard")}
          </NavLink>
          <NavLink to="/sales" className={({ isActive }) => (isActive ? "active" : "")}>
            {t("nav.sales")}
          </NavLink>
          <NavLink to="/audit" className={({ isActive }) => (isActive ? "active" : "")}>
            {t("nav.audit")}
          </NavLink>
        </nav>
      </div>
      <div className="topbar-right">
        <div className="scope-chip">
          <b>{user?.company ?? "—"}</b>
          <span className="dot" />
          <span>{user?.display_name}</span>
          <span className="dot" />
          <span>₹ INR</span>
        </div>
        <select className="lang" value={lang} onChange={(e) => setLang(e.target.value as Lang)} aria-label="Language">
          <option value="en">EN — English</option>
          <option value="ml">ML — മലയാളം</option>
        </select>
        <ThemeToggle />
        <button className="ask-btn" onClick={open}>
          <span className="spark">✦</span> <span>{t("nav.ask")}</span>
        </button>
        <button className="icon-btn" style={{ color: "rgba(255,255,255,.65)" }} onClick={logout} title="Sign out" aria-label="Sign out">
          ⏻
        </button>
      </div>
    </header>
  );
}
