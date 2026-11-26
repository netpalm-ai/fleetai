import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link, NavLink } from "react-router-dom";
import { useSession } from "../session";
import { BrandMark } from "./BrandMark";

const NAV = [
  { to: "/tickets", label: "Tickets", end: true },
  { to: "/connectors", label: "Connectors", end: true },
  { to: "/settings", label: "Settings", end: true },
] as const;

export function AppShell({ children }: { children: ReactNode }) {
  const { username, signOut } = useSession();
  const [open, setOpen] = useState(false);
  const menu = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) {
      return;
    }
    function onPointer(event: MouseEvent) {
      if (menu.current && !menu.current.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div className="app-shell">
      <aside className="app-sidebar">
        <Link to="/tickets" className="app-sidebar-brand">
          <BrandMark />
        </Link>
        <nav className="app-sidebar-nav" aria-label="Main">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) => (isActive ? "app-nav-link on" : "app-nav-link")}
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
      </aside>
      <div className="app-frame">
        <header className="app-top">
          <div className="app-top-end" ref={menu}>
            <button
              className="btn btn-ghost app-user-btn"
              type="button"
              aria-expanded={open}
              aria-haspopup="menu"
              onClick={() => setOpen((value) => !value)}
            >
              {username}
            </button>
            {open ? (
              <div className="app-user-menu" role="menu">
                <Link to="/settings" role="menuitem" onClick={() => setOpen(false)}>
                  Settings
                </Link>
                <button
                  type="button"
                  role="menuitem"
                  onClick={() => {
                    setOpen(false);
                    void signOut();
                  }}
                >
                  Sign out
                </button>
              </div>
            ) : null}
          </div>
        </header>
        <div className="app-content">{children}</div>
      </div>
    </div>
  );
}
