import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Navigate } from "react-router-dom";
import { ApiError, getJson, request } from "../api/client";
import { AppHeader } from "../components/AppHeader";
import { AuthenticatorSetup } from "../components/AuthenticatorSetup";
import { useSession } from "../session";
import type { Settings } from "../types";

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
        <AuthenticatorSetup onError={fail} />
      </main>
    </>
  );
}
