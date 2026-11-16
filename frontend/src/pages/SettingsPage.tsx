import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Navigate } from "react-router-dom";
import { ApiError, getJson, request } from "../api/client";
import { AppHeader } from "../components/AppHeader";
import { AuthenticatorSetup } from "../components/AuthenticatorSetup";
import { useSession } from "../session";
import type { GithubStatus, Settings } from "../types";

const PERMANENT = "permanent";
const KEEP_OPTIONS = [
  { value: "7", label: "7 days" },
  { value: "30", label: "30 days" },
  { value: "90", label: "90 days" },
  { value: PERMANENT, label: "Permanent" },
];

function keepText(days: number | null): string {
  if (days === null) {
    return "Handled tickets stay visible permanently. They are kept for audit either way.";
  }
  if (days === 0) {
    return "Handled tickets are hidden as soon as they are fixed or completed. They are kept for audit.";
  }
  return (
    "Handled tickets stay visible for " +
    String(days) +
    " days after they are fixed or completed. They are kept for audit either way."
  );
}

export function SettingsPage() {
  const { username, ready, expire } = useSession();
  const [settings, setSettings] = useState<Settings | null>(null);
  const [keep, setKeep] = useState("90");
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [github, setGithub] = useState<GithubStatus | null>(null);
  const [project, setProject] = useState("");
  const [chosen, setChosen] = useState<string[]>([]);
  const [githubSaved, setGithubSaved] = useState(false);

  const show = useCallback((next: Settings) => {
    setSettings(next);
    setKeep(next.ticket_retention_days === null ? PERMANENT : String(next.ticket_retention_days));
  }, []);

  const fail = useCallback(
    (err: unknown) => {
      if (err instanceof ApiError && err.status === 401) {
        expire();
        return;
      }
      setError(err instanceof Error ? err.message : "request failed");
    },
    [expire],
  );

  useEffect(() => {
    if (username) {
      getJson<Settings>("/settings").then(show).catch(fail);
      getJson<GithubStatus>("/github")
        .then((next) => {
          setGithub(next);
          setProject(next.project || "");
          setChosen(next.repos.filter((repo) => repo.selected).map((repo) => repo.full_name));
        })
        .catch(fail);
    }
  }, [fail, show, username]);

  async function onSave(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setSaved(false);
    try {
      show(
        await request<Settings>("/settings", {
          method: "PUT",
          body: JSON.stringify({ ticket_retention_days: keep === PERMANENT ? null : Number(keep) }),
        }),
      );
      setSaved(true);
    } catch (err: unknown) {
      fail(err);
    }
  }

  if (!ready) {
    return null;
  }
  if (!username) {
    return <Navigate to="/login" replace />;
  }

  return (
    <>
      <AppHeader />
      <main className="shell shell-wide">
        <div className="page-head">
          <div>
            <p className="eyebrow">Account</p>
            <h1>Settings</h1>
          </div>
        </div>
        {error ? <p className="form-error studio-error">{error}</p> : null}
        {settings ? (
          <section className="board settings">
            <div className="board-head">
              <h2>Ticket history</h2>
            </div>
            <p className="muted">Plan: {settings.subscription_status}</p>
            <p className="muted">{keepText(settings.ticket_retention_days)}</p>
            {settings.editable ? (
              <form onSubmit={(event) => void onSave(event)}>
                <label className="field">
                  Show handled tickets for
                  <select value={keep} onChange={(event) => setKeep(event.target.value)}>
                    {KEEP_OPTIONS.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </label>
                <button className="btn btn-primary btn-block" type="submit">
                  Save
                </button>
                {saved ? <p className="muted">Saved.</p> : null}
              </form>
            ) : null}
          </section>
        ) : null}
        <section className="board settings">
          <div className="board-head">
            <h2>GitHub</h2>
          </div>
          {new URLSearchParams(window.location.search).get("github") === "failed" ? (
            <p className="form-error">GitHub did not connect. Try again.</p>
          ) : null}
          {github == null ? null : !github.configured ? (
            <p className="muted">GitHub is not configured.</p>
          ) : !github.connected ? (
            <>
              <p className="muted">
                Connect a GitHub account to clone its repositories and push fixes to fleetai/dev.
              </p>
              <button
                className="btn btn-primary"
                type="button"
                onClick={() => window.location.assign("/api/v1/github/connect")}
              >
                Connect GitHub
              </button>
            </>
          ) : (
            <>
              <p className="muted">Connected as {github.login}. Fixes push to fleetai/dev.</p>
              <form
                onSubmit={(event) => {
                  event.preventDefault();
                  setGithubSaved(false);
                  request<GithubStatus>("/github/repos", {
                    method: "PUT",
                    body: JSON.stringify({ project, repos: chosen }),
                  })
                    .then((next) => {
                      setGithub(next);
                      setProject(next.project || "");
                      setGithubSaved(true);
                    })
                    .catch(fail);
                }}
              >
                <label className="field">
                  Project name
                  <input
                    value={project}
                    maxLength={64}
                    onChange={(event) => setProject(event.target.value)}
                  />
                </label>
                <div className="repo-list">
                  {github.repos.map((repo) => (
                    <label className="accept" key={repo.full_name}>
                      <input
                        type="checkbox"
                        checked={chosen.includes(repo.full_name)}
                        onChange={(event) => {
                          setChosen((current) =>
                            event.target.checked
                              ? current.concat(repo.full_name)
                              : current.filter((name) => name !== repo.full_name),
                          );
                        }}
                      />
                      <span>{repo.full_name}</span>
                    </label>
                  ))}
                </div>
                <button className="btn btn-primary" type="submit">
                  Save repositories
                </button>
                {githubSaved ? <p className="muted">Saved.</p> : null}
              </form>
              <button
                className="btn"
                type="button"
                onClick={() => {
                  request<void>("/github", { method: "DELETE" })
                    .then(() =>
                      setGithub({ configured: true, connected: false, login: null, project: null, repos: [] }),
                    )
                    .catch(fail);
                }}
              >
                Disconnect
              </button>
            </>
          )}
        </section>
        <AuthenticatorSetup onError={fail} />
      </main>
    </>
  );
}
