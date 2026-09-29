import { NavLink } from "react-router-dom";
import { ThemeToggle } from "../components/ThemeToggle";
import { NavDropdown } from "./NavDropdown";
import { useLanguage } from "../i18n/LanguageProvider";
import { useAskErp } from "../askerp/AskErpContext";
import { useAuth } from "../auth/AuthProvider";
import { hasPermission } from "../auth/permissions";
import type { Lang } from "../i18n/strings";

export function TopBar() {
  const { t, lang, setLang } = useLanguage();
  const { open } = useAskErp();
  const { user, logout } = useAuth();

  const salesItems = [
    { to: "/sales", label: t("nav.sales") },
    ...(hasPermission(user, "sales.customer.read") ? [{ to: "/customers", label: "Customers" }] : []),
    ...(hasPermission(user, "inventory.item.read") ? [{ to: "/items", label: "Items" }] : []),
  ];

  const crmItems = [
    ...(hasPermission(user, "crm.lead.read") ? [{ to: "/leads", label: "Leads" }] : []),
    // Customer is shared master data, not Sales- or CRM-owned (matches the
    // blueprint grouping Lead/Contact/Customer/Opportunity as one
    // "Commercial" domain) — listed here too so CRM work never requires a
    // detour into the Sales menu.
    ...(hasPermission(user, "sales.customer.read") ? [{ to: "/customers", label: "Customers" }] : []),
    ...(hasPermission(user, "crm.contact.read") ? [{ to: "/contacts", label: "Contacts" }] : []),
    ...(hasPermission(user, "crm.opportunity.read") ? [{ to: "/opportunities", label: "Opportunities" }] : []),
    ...(hasPermission(user, "crm.activity.read") ? [{ to: "/activities", label: "Activities" }] : []),
  ];

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
          <NavDropdown label="Sales" items={salesItems} />
          {crmItems.length > 0 && <NavDropdown label="CRM" items={crmItems} />}
          <NavLink to="/audit" className={({ isActive }) => (isActive ? "active" : "")}>
            {t("nav.audit")}
          </NavLink>
          {hasPermission(user, "admin.users.read") && (
            <NavLink to="/admin" className={({ isActive }) => (isActive ? "active" : "")}>
              Admin
            </NavLink>
          )}
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
