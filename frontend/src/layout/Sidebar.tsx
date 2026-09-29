import { NavLink, useLocation } from "react-router-dom";
import { BrandMark, Icon, type IconName } from "../components/Icon";
import { useAskErp } from "../askerp/AskErpContext";
import { useAppData } from "../data/AppDataProvider";

interface NavItem {
  to?: string;
  label: string;
  icon: IconName;
  count?: number;
  end?: boolean;
}

/**
 * Left navigation from the design. Modules with no backend yet are listed
 * but disabled and tagged "Soon", so the roadmap is visible without links
 * that lead nowhere.
 */
export function Sidebar({ open, onNavigate }: { open: boolean; onNavigate: () => void }) {
  const { activities, quotes, can } = useAppData();
  const { open: openAsk } = useAskErp();
  const location = useLocation();
  // CRM and the Approvals shortcut share /crm; the query decides which one is lit.
  const onApprovals = location.pathname === "/crm" && location.search.includes("status=pending");
  const overdue = activities.filter((a) => a.is_overdue).length;
  const pending = quotes.filter((q) => q.status === "Pending approval").length;

  const items: NavItem[] = [
    { to: "/", label: "Overview", icon: "home", end: true },
    { label: "Ask ERP", icon: "chat" },
    { to: "/crm", label: "CRM & Sales", icon: "users", count: overdue },
    { label: "Inventory", icon: "box" },
    { label: "Purchasing", icon: "cart" },
    { label: "Finance", icon: "chart" },
    { label: "HR & Payroll", icon: "user" },
    { label: "Reports", icon: "file" },
    { to: "/crm?tab=quotations&status=pending", label: "Approvals", icon: "check", count: pending },
  ];
  if (can("audit.read")) items.push({ to: "/audit", label: "AI audit trail", icon: "shield" });

  return (
    <>
      <div className={`nav-scrim${open ? " open" : ""}`} onClick={onNavigate} />
      <aside className={`sidebar${open ? " open" : ""}`} aria-label="Main navigation">
        <NavLink to="/" className="brand" onClick={onNavigate}>
          <BrandMark /> ALBIRUNI <small>ERP</small>
        </NavLink>
        <nav className="side-nav">
          {items.map((item) => {
            if (item.label === "Ask ERP") {
              return (
                <button
                  key={item.label}
                  className="nav-action"
                  onClick={() => {
                    openAsk();
                    onNavigate();
                  }}
                >
                  <Icon name={item.icon} size={22} /> {item.label}
                </button>
              );
            }
            if (!item.to) {
              return (
                <span key={item.label} className="soon" aria-disabled="true" title="Not built yet">
                  <Icon name={item.icon} size={22} /> {item.label} <span className="tag">Soon</span>
                </span>
              );
            }
            return (
              <NavLink
                key={item.label}
                to={item.to}
                end={item.end}
                onClick={onNavigate}
                className={({ isActive }) => {
                  if (item.label === "Approvals") return onApprovals ? "active" : "";
                  if (item.label === "CRM & Sales") return isActive && !onApprovals ? "active" : "";
                  return isActive ? "active" : "";
                }}
              >
                <Icon name={item.icon} size={22} /> {item.label}
                {!!item.count && <span className="count">{item.count}</span>}
              </NavLink>
            );
          })}
        </nav>
        <div className="sidebar-bottom">
          <div className="side-nav">
            <span className="soon" aria-disabled="true" title="Not built yet">
              <Icon name="settings" size={22} /> Settings <span className="tag">Soon</span>
            </span>
          </div>
          <div className="sidebar-tagline">
            <svg viewBox="0 0 200 90" aria-hidden="true">
              <path d="M0 90 L70 40 L95 55 L140 10 L200 70 L200 90 Z" fill="#15a88c" opacity="0.35" />
              <path d="M40 90 L110 35 L150 65 L200 45 L200 90 Z" fill="#2fd1a8" opacity="0.25" />
            </svg>
            <span>
              Smarter operations
              <br />
              for a brighter tomorrow.
            </span>
          </div>
        </div>
      </aside>
    </>
  );
}
