import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { Navigate, useLocation, useSearchParams } from "react-router-dom";
import { getJson, request, requestError } from "../api/client";
import { GithubMark } from "../components/GithubMark";
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
  const { username } = useSession();
  const location = useLocation();
  const [params] = useSearchParams();
  const connectors = location.pathname === "/connectors" || params.has("github");
  const [settings, setSettings] = useState<Settings | null>(null);
  const [keep, setKeep] = useState("90");
  const [error, setError] = useState<string | null>(null);
  const [keepError, setKeepError] = useState<string | null>(null);
  const [projectError, setProjectError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [saving, setSaving] = useState(false);
  const saveLock = useRef(false);
  const [github, setGithub] = useState<GithubStatus | null>(null);
  const [project, setProject] = useState("");
  const [chosen, setChosen] = useState<string[]>([]);
  const [githubSaved, setGithubSaved] = useState(false);
  const [githubSaving, setGithubSaving] = useState(false);
  const [settingsLoadFailed, setSettingsLoadFailed] = useState(false);
  const [githubLoadFailed, setGithubLoadFailed] = useState(false);
  const githubLock = useRef(false);

  const show = useCallback((next: Settings) => {
    setSettings(next);
    setKeep(next.ticket_retention_days === null ? PERMANENT : String(next.ticket_retention_days));
  }, []);

  const fail = useCallback((err: unknown) => {
    const message = requestError(err, "Something went wrong. Try again.");
    if (message) {
      setError(message);
    }
    return message;
  }, []);

  useEffect(() => {
    if (!username) {
      return;
    }
    if (connectors) {
      setGithubLoadFailed(false);
      getJson<GithubStatus>("/github")
        .then((next) => {
          setGithub(next);
          setProject(next.project || "");
          setChosen(next.repos.filter((repo) => repo.selected).map((repo) => repo.full_name));
        })
        .catch((err: unknown) => {
          if (fail(err)) {
            setGithubLoadFailed(true);
          }
        });
      return;
    }
    setSettingsLoadFailed(false);
    getJson<Settings>("/settings")
      .then(show)
      .catch((err: unknown) => {
        if (fail(err)) {
          setSettingsLoadFailed(true);
        }
      });
  }, [connectors, fail, show, username]);

  async function onSave(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (saveLock.current) {
      return;
    }
    saveLock.current = true;
    setSaving(true);
    setError(null);
    setKeepError(null);
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
      const message = requestError(err, "Could not save settings.");
      if (message) {
        setKeepError(message);
      }
    } finally {
      saveLock.current = false;
      setSaving(false);
    }
  }

  if (location.pathname === "/settings" && (params.get("tab") === "connectors" || params.has("github"))) {
    const next = new URLSearchParams();
    const github = params.get("github");
    if (github) {
      next.set("github", github);
    }
    const query = next.toString();
    return <Navigate to={query ? "/connectors?" + query : "/connectors"} replace />;
  }

  return (
      <main className="shell shell-app">
        <div className="page-head">
          <div>
            <p className="eyebrow">{connectors ? "Workspace" : "Account"}</p>
            <h1>{connectors ? "Connectors" : "Settings"}</h1>
          </div>
        </div>
        {error ? (
          <p className="form-error studio-error" role="alert">
            {error}
          </p>
        ) : null}
        {connectors ? (
          <section className="board settings" id="connectors">
            <div className="board-head">
              <h2 className="with-icon">
                <GithubMark />
                GitHub
              </h2>
            </div>
            {params.get("github") === "failed" ? (
              <p className="form-error" role="alert">
                GitHub did not connect. Try again.
              </p>
            ) : null}
            {github == null ? (
              <p className="muted">{githubLoadFailed ? "Could not load connectors." : "Loading connectors…"}</p>
            ) : !github.connected ? (
              <button
                  className="btn btn-primary btn-block with-icon"
                  type="button"
                  onClick={() => {
                    if (!github.configured) {
                      setError("GitHub could not be connected. Try again later.");
                      return;
                    }
                    window.location.assign("/api/v1/github/connect");
                  }}
                >
                  <GithubMark />
                  Connect GitHub
                </button>
            ) : (
              <>
                <p className="muted with-icon">
                  <GithubMark />
                  Connected as {github.login}.
                </p>
                <p className="muted">Choose the repositories FleetAI should use.</p>
                <form
                  onSubmit={(event) => {
                    event.preventDefault();
                    if (githubLock.current) {
                      return;
                    }
                    githubLock.current = true;
                    setGithubSaving(true);
                    setGithubSaved(false);
                    setProjectError(null);
                    request<GithubStatus>("/github/repos", {
                      method: "PUT",
                      body: JSON.stringify({ project, repos: chosen }),
                    })
                      .then((next) => {
                        setGithub(next);
                        setProject(next.project || "");
                        setGithubSaved(true);
                      })
                      .catch((err: unknown) => {
                        const message = requestError(err, "Could not save repositories.");
                        if (message) {
                          setProjectError(message);
                        }
                      })
                      .finally(() => {
                        githubLock.current = false;
                        setGithubSaving(false);
                      });
                  }}
                >
                  <label className="field">
                    Project name
                    <input
                      value={project}
                      maxLength={64}
                      onChange={(event) => setProject(event.target.value)}
                      aria-invalid={projectError ? true : undefined}
                      aria-describedby={projectError ? "github-project-error" : undefined}
                    />
                    {projectError ? (
                      <p className="form-error" id="github-project-error" role="alert">
                        {projectError}
                      </p>
                    ) : null}
                  </label>
                  {github.repos.length === 0 ? (
                    <p className="muted">No repositories to choose yet.</p>
                  ) : (
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
                  )}
                  <button className="btn btn-primary btn-block" type="submit" disabled={githubSaving}>
                    Save repositories
                  </button>
                  {githubSaved ? <p className="muted">Saved.</p> : null}
                </form>
                <button
                  className="btn btn-ghost btn-block"
                  type="button"
                  onClick={() => {
                    request<void>("/github", { method: "DELETE" })
                      .then(() =>
                        setGithub({
                          configured: true,
                          connected: false,
                          login: null,
                          project: null,
                          repos: [],
                        }),
                      )
                      .catch(fail);
                  }}
                >
                  Disconnect
                </button>
              </>
            )}
          </section>
        ) : (
          <>
            {settings ? (
              <section className="board settings">
                <div className="board-head">
                  <h2>Ticket history</h2>
                </div>
                <p className="muted">
                  Plan: {settings.subscription_status.charAt(0).toUpperCase() + settings.subscription_status.slice(1)}
                </p>
                <p className="muted">{keepText(settings.ticket_retention_days)}</p>
                {settings.editable ? (
                  <form onSubmit={(event) => void onSave(event)}>
                    <label className="field">
                      Show handled tickets for
                      <select
                        value={keep}
                        onChange={(event) => setKeep(event.target.value)}
                        aria-invalid={keepError ? true : undefined}
                        aria-describedby={keepError ? "settings-keep-error" : undefined}
                      >
                        {KEEP_OPTIONS.map((option) => (
                          <option key={option.value} value={option.value}>
                            {option.label}
                          </option>
                        ))}
                      </select>
                      {keepError ? (
                        <p className="form-error" id="settings-keep-error" role="alert">
                          {keepError}
                        </p>
                      ) : null}
                    </label>
                    <button className="btn btn-primary btn-block" type="submit" disabled={saving}>
                      Save
                    </button>
                    {saved ? <p className="muted">Saved.</p> : null}
                  </form>
                ) : null}
              </section>
            ) : (
              <p className="muted">{settingsLoadFailed ? "Could not load settings." : "Loading settings…"}</p>
            )}
            <AuthenticatorSetup onError={fail} />
          </>
        )}
      </main>
  );
}
