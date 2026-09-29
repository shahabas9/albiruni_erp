import { useEffect, useRef, useState } from "react";
import { NavLink, useLocation } from "react-router-dom";

interface NavItem {
  to: string;
  label: string;
}

/** A labeled group of nav links, collapsed behind a click-to-open popover.
 * Exists because a flat top-level nav stops working somewhere around 8-10
 * items — grouping related routes (Sales, CRM) keeps the header scannable
 * as more modules land. */
export function NavDropdown({ label, items }: { label: string; items: NavItem[] }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const location = useLocation();
  const isActive = items.some((i) => location.pathname === i.to);

  useEffect(() => {
    function onClickOutside(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, []);

  useEffect(() => {
    setOpen(false);
  }, [location.pathname]);

  return (
    <div className="nav-dropdown" ref={ref}>
      <button className={`nav-dropdown-trigger${isActive ? " active" : ""}`} onClick={() => setOpen((v) => !v)}>
        {label} <span className="nav-dropdown-caret">{open ? "▴" : "▾"}</span>
      </button>
      {open && (
        <div className="nav-dropdown-menu">
          {items.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive: linkActive }) => (linkActive ? "active" : "")}
            >
              {item.label}
            </NavLink>
          ))}
        </div>
      )}
    </div>
  );
}

export type { NavItem };
