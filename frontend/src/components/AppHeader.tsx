import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getJson } from "../api/client";
import { useSession } from "../session";
import type { GithubStatus } from "../types";
import { BrandMark } from "./BrandMark";
import { GithubMark } from "./GithubMark";

export function AppHeader() {
  const { username, signOut } = useSession();
  const [github, setGithub] = useState<GithubStatus | null>(null);

  useEffect(() => {
    if (!username) {
      return;
    }
    getJson<GithubStatus>("/github")
      .then(setGithub)
      .catch(() => setGithub(null));
  }, [username]);

  return (
    <header className="site-header">
      <div className="nav nav-wide">
        <Link to="/">
          <BrandMark />
        </Link>
        <div className="nav-end">
          {github == null ? null : github.connected ? (
            <Link to="/settings#github" className="btn btn-ghost with-icon">
              <GithubMark />
              {github.login}
            </Link>
          ) : (
            <button
              className="btn btn-ghost with-icon"
              type="button"
              onClick={() => {
                if (github.configured) {
                  window.location.assign("/api/v1/github/connect");
                  return;
                }
                window.location.assign("/settings#github");
              }}
            >
              <GithubMark />
              Connect GitHub
            </button>
          )}
          <span className="nav-user">{username}</span>
          <Link to="/settings" className="btn btn-ghost">
            Settings
          </Link>
          <button type="button" className="btn btn-ghost" onClick={() => void signOut()}>
            Sign out
          </button>
        </div>
      </div>
    </header>
  );
}
