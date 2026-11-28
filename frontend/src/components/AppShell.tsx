import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link, NavLink, useLocation, useSearchParams } from "react-router-dom";
import { getJson } from "../api/client";
import { TERMS_TITLE } from "../data/termsOfService";
import { useSession } from "../session";
import type { Project } from "../types";
import { BrandMark } from "./BrandMark";

const NAV = [
  { to: "/connectors", label: "Connectors", end: true, icon: "plug" },
  { to: "/settings", label: "Settings", end: true, icon: "gear" },
] as const;

function titleFor(pathname: string): string {
  if (pathname === "/tickets") {
    return "Tickets";
  }
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
  const [params] = useSearchParams();
  const [open, setOpen] = useState(false);
  const [projectsOpen, setProjectsOpen] = useState(pathname === "/tickets");
  const [projects, setProjects] = useState<Project[]>([]);
  const menu = useRef<HTMLDivElement>(null);
  const title = titleFor(pathname);
  const selectedProject = params.get("project");

  useEffect(() => {
    if (pathname === "/tickets") {
      setProjectsOpen(true);
    }
  }, [pathname]);

  useEffect(() => {
    if (!username) {
      setProjects([]);
      return;
    }
    let cancel = false;
    getJson<Project[]>("/projects")
      .then((rows) => {
        if (!cancel) {
          setProjects(rows);
        }
      })
      .catch(() => {
        if (!cancel) {
          setProjects([]);
        }
      });
    return () => {
      cancel = true;
    };
  }, [username]);

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
            <div className="app-nav-group">
              <button
                className="app-nav-link"
                type="button"
                aria-expanded={projectsOpen}
                onClick={() => setProjectsOpen((value) => !value)}
              >
                <NavIcon name="folder" />
                <span className="app-nav-label">Projects</span>
                <NavIcon name={projectsOpen ? "chevron-down" : "chevron"} />
              </button>
              {projectsOpen ? (
                <div className="app-nav-projects">
                  {projects.map((project) => {
                    const selected = pathname === "/tickets" && selectedProject === project.id;
                    return (
                      <Link
                        key={project.id}
                        to={"/tickets?project=" + encodeURIComponent(project.id)}
                        className={selected ? "app-nav-link app-nav-project on" : "app-nav-link app-nav-project"}
                      >
                        <NavIcon name="box" />
                        <span className="app-nav-label">{project.product_name || project.name}</span>
                      </Link>
                    );
                  })}
                </div>
              ) : null}
            </div>
            {NAV.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) => (isActive ? "app-nav-link on" : "app-nav-link")}
              >
                <NavIcon name={item.icon} />
                <span className="app-nav-label">{item.label}</span>
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

function NavIcon({ name }: { name: "folder" | "plug" | "gear" | "box" | "chevron" | "chevron-down" }) {
  const common = {
    className: "app-nav-icon",
    viewBox: "0 0 16 16",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.5,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    "aria-hidden": true,
  };
  if (name === "folder") {
    return (
      <svg {...common}>
        <path d="M2 4.5h4l1.2 1.5H14v7H2z" />
      </svg>
    );
  }
  if (name === "plug") {
    return (
      <svg {...common}>
        <path d="M6 2.5v3M10 2.5v3M4.5 6.5h7v2a3.5 3.5 0 0 1-7 0zM8 12v1.5" />
      </svg>
    );
  }
  if (name === "gear") {
    return (
      <svg {...common}>
        <circle cx="8" cy="8" r="2" />
        <path d="M8 1.8v1.7M8 12.5v1.7M1.8 8h1.7M12.5 8h1.7M3.4 3.4l1.2 1.2M11.4 11.4l1.2 1.2M12.6 3.4l-1.2 1.2M4.6 11.4l-1.2 1.2" />
      </svg>
    );
  }
  if (name === "box") {
    return (
      <svg {...common}>
        <path d="M3 5.5 8 3l5 2.5v5L8 13l-5-2.5zM3 5.5 8 8l5-2.5M8 8v5" />
      </svg>
    );
  }
  if (name === "chevron-down") {
    return (
      <svg {...common}>
        <path d="M4 6.5 8 10.5 12 6.5" />
      </svg>
    );
  }
  return (
    <svg {...common}>
      <path d="M6 4.5 10 8 6 11.5" />
    </svg>
  );
}
