import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link, NavLink, useLocation } from "react-router-dom";
import { TERMS_TITLE } from "../data/termsOfService";
import { useSession } from "../session";
import { BrandMark } from "./BrandMark";

const NAV = [
  { to: "/tickets", label: "Tickets", end: true },
  { to: "/connectors", label: "Connectors", end: true },
  { to: "/settings", label: "Settings", end: true },
] as const;

function titleFor(pathname: string): string {
  const item = NAV.find((entry) => entry.to === pathname);
  if (item) {
    return item.label;
  }
  switch (pathname) {
    case "/":
      return "Home";
    case "/login":
      return "Sign in";
    case "/signup":
      return "Create an account";
    case "/forgot":
      return "Reset password";
    case "/reset":
      return "Choose a new password";
    case "/verify":
      return "Verify email";
    case "/terms":
      return TERMS_TITLE;
    default:
      return "";
  }
}

export function AppShell({ children }: { children: ReactNode }) {
  const { username, ready, signOut } = useSession();
  const { pathname } = useLocation();
  const [open, setOpen] = useState(false);
  const menu = useRef<HTMLDivElement>(null);
  const title = titleFor(pathname);

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
        <Link to={username ? "/tickets" : "/"} className="app-sidebar-brand">
          <BrandMark />
        </Link>
        {username ? (
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
        ) : null}
        <div className="app-sidebar-account" ref={menu}>
          {username ? (
            <>
              <button
                className="app-user-btn"
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
            </>
          ) : ready ? (
            <Link className="app-account-link" to="/login">
              Sign in
            </Link>
          ) : null}
        </div>
      </aside>
      <div className="app-frame">
        <header className="app-top">
          {title ? <p className="app-title">{title}</p> : null}
        </header>
        <div className="app-content">{children}</div>
      </div>
    </div>
  );
}
