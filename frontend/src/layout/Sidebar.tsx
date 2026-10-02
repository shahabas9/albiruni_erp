import { useEffect, useState } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { BrandMark, Icon, type IconName } from "../components/Icon";
import { useAskErp } from "../askerp/AskErpContext";
import { useAppData } from "../data/AppDataProvider";

interface NavLinkItem {
  to: string;
  label: string;
  count?: number;
  permission?: string;
}

interface NavGroup {
  id: string;
  label: string;
  icon: IconName;
  children: NavLinkItem[];
}

/** Disabled roadmap entries: listed so the module map is visible, but no links that lead nowhere. */
const SOON: { label: string; icon: IconName }[] = [
  { label: "Purchasing", icon: "cart" },
  { label: "Finance", icon: "chart" },
  { label: "HR & Payroll", icon: "user" },
  { label: "Reports", icon: "file" },
];

const STORAGE_KEY = "albiruni-nav-open";

function readOpenGroups(): Record<string, boolean> {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "{}");
  } catch {
    return {};
  }
}

/** A child link is active on an exact path match; a `?query` in its target must match too. */
function isChildActive(to: string, pathname: string, search: string): boolean {
  const [path, query] = to.split("?");
  if (path !== pathname) return false;
  const params = new URLSearchParams(search);
  if (!query) return !params.has("status");
  return [...new URLSearchParams(query)].every(([k, v]) => params.get(k) === v);
}

/** The menu entry for the current page: an exact match, else the entry whose
 * path is the longest prefix of it (so /sales/orders/123 lights up Orders). */
function activeLinkFor(links: string[], pathname: string, search: string): string | undefined {
  const exact = links.find((to) => isChildActive(to, pathname, search));
  if (exact) return exact;
  return links
    .filter((to) => !to.includes("?") && pathname.startsWith(`${to}/`))
    .sort((a, b) => b.length - a.length)[0];
}

export function Sidebar({ open, onNavigate }: { open: boolean; onNavigate: () => void }) {
  const { crm, quotes, can } = useAppData();
  const { open: openAsk } = useAskErp();
  const { pathname, search } = useLocation();
  const overdue = crm?.overdue_followups ?? 0;
  const pending = quotes.filter((q) => q.status === "Pending approval").length;

  const allGroups: NavGroup[] = [
    {
      id: "crm",
      label: "CRM",
      icon: "users",
      children: [
        { to: "/crm", label: "Pipeline", permission: "crm.opportunity.read" },
        { to: "/leads", label: "Leads", permission: "crm.lead.read" },
        { to: "/opportunities", label: "Opportunities", permission: "crm.opportunity.read" },
        { to: "/contacts", label: "Contacts", permission: "crm.contact.read" },
        { to: "/activities", label: "Activities", permission: "crm.activity.read", count: overdue },
        { to: "/crm/targets", label: "Targets", permission: "crm.opportunity.read" },
        { to: "/crm/settings", label: "Settings", permission: "crm.settings.write" },
      ],
    },
    {
      id: "sales",
      label: "Sales",
      icon: "file",
      children: [
        { to: "/sales/quick-sale", label: "Quick sale", permission: "sales.invoice.write" },
        { to: "/sales", label: "Quotations", permission: "sales.quotation.read" },
        { to: "/sales/orders", label: "Orders", permission: "sales.order.read" },
        { to: "/sales/deliveries", label: "Deliveries", permission: "sales.order.read" },
        { to: "/sales/invoices", label: "Invoices", permission: "sales.invoice.read" },
        { to: "/sales/credit-notes", label: "Credit notes", permission: "sales.invoice.read" },
        { to: "/sales/payments", label: "Payments", permission: "sales.payment.read" },
        { to: "/sales/refunds", label: "Refunds", permission: "sales.payment.read" },
        { to: "/sales/receivables", label: "Receivables", permission: "sales.invoice.read" },
        { to: "/sales/reports", label: "Reports", permission: "sales.reports.read" },
        { to: "/customers", label: "Customers", permission: "sales.customer.read" },
        { to: "/sales?status=pending", label: "Approvals", permission: "sales.quotation.read", count: pending },
        { to: "/sales/price-lists", label: "Price lists", permission: "sales.settings.write" },
        { to: "/sales/settings", label: "Company & Tax", permission: "sales.settings.write" },
      ],
    },
    {
      id: "inventory",
      label: "Inventory",
      icon: "box",
      children: [{ to: "/items", label: "Items", permission: "inventory.item.read" }],
    },
    {
      id: "admin",
      label: "Administration",
      icon: "shield",
      children: [
        { to: "/admin", label: "Users & Roles", permission: "admin.users.read" },
        { to: "/audit", label: "AI audit trail", permission: "audit.read" },
      ],
    },
  ];
  const groups = allGroups
    .map((g) => ({ ...g, children: g.children.filter((c) => !c.permission || can(c.permission)) }))
    .filter((g) => g.children.length > 0);

  const activeTo = activeLinkFor(groups.flatMap((g) => g.children.map((c) => c.to)), pathname, search);
  const activeGroup = groups.find((g) => g.children.some((c) => c.to === activeTo))?.id;
  const [expanded, setExpanded] = useState<Record<string, boolean>>(readOpenGroups);

  // Landing on a page (link, notification, back button) always reveals its group.
  useEffect(() => {
    if (activeGroup) setExpanded((prev) => (prev[activeGroup] ? prev : { ...prev, [activeGroup]: true }));
  }, [activeGroup]);

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(expanded));
    } catch {
      // Non-fatal: groups just won't remember their state.
    }
  }, [expanded]);

  const toggle = (id: string) => setExpanded((prev) => ({ ...prev, [id]: !prev[id] }));

  return (
    <>
      <div className={`nav-scrim${open ? " open" : ""}`} onClick={onNavigate} />
      <aside className={`sidebar${open ? " open" : ""}`} aria-label="Main navigation">
        <NavLink to="/" className="brand" onClick={onNavigate}>
          <BrandMark /> ALBIRUNI <small>ERP</small>
        </NavLink>
        <nav className="side-nav">
          <NavLink to="/" end onClick={onNavigate} className={({ isActive }) => (isActive ? "active" : "")}>
            <Icon name="home" size={22} /> Overview
          </NavLink>
          <button
            className="nav-action"
            onClick={() => {
              openAsk();
              onNavigate();
            }}
          >
            <Icon name="chat" size={22} /> Ask ERP
          </button>

          {groups.map((g) => {
            const isOpen = !!expanded[g.id];
            const total = g.children.reduce((s, c) => s + (c.count ?? 0), 0);
            return (
              <div className="side-group" key={g.id}>
                <button
                  className={`side-group-btn${activeGroup === g.id ? " has-active" : ""}`}
                  aria-expanded={isOpen}
                  aria-controls={`nav-${g.id}`}
                  onClick={() => toggle(g.id)}
                >
                  <Icon name={g.icon} size={22} /> {g.label}
                  {!isOpen && total > 0 && <span className="count">{total}</span>}
                  <Icon name="down" size={16} className={`chev${isOpen ? " open" : ""}`} />
                </button>
                {isOpen && (
                  <div className="side-sub" id={`nav-${g.id}`}>
                    {g.children.map((c) => (
                      <NavLink
                        key={c.to}
                        to={c.to}
                        end
                        onClick={onNavigate}
                        className={() => (c.to === activeTo ? "active" : "")}
                      >
                        {c.label}
                        {!!c.count && <span className="count">{c.count}</span>}
                      </NavLink>
                    ))}
                  </div>
                )}
              </div>
            );
          })}

          {SOON.map((s) => (
            <span key={s.label} className="soon" aria-disabled="true" title="Not built yet">
              <Icon name={s.icon} size={22} /> {s.label} <span className="tag">Soon</span>
            </span>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="side-nav">
            <span className="soon" aria-disabled="true" title="Not built yet">
              <Icon name="settings" size={22} /> Settings <span className="tag">Soon</span>
            </span>
          </div>
          <div className="sidebar-tagline">
            <svg viewBox="0 0 200 90" aria-hidden="true">
              <path d="M0 90 L70 40 L95 55 L140 10 L200 70 L200 90 Z" fill="#23b1aa" opacity="0.35" />
              <path d="M40 90 L110 35 L150 65 L200 45 L200 90 Z" fill="#3fd0c6" opacity="0.25" />
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
