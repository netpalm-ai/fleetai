import { useCallback, useEffect, useState } from "react";
import { Navigate } from "react-router-dom";
import { ApiError, getJson } from "../api/client";
import { BrandMark } from "../components/BrandMark";
import { useSession } from "../session";
import type { Ticket } from "../types";

export function TicketsPage() {
  const { username, ready, signOut } = useSession();
  const [tickets, setTickets] = useState<Ticket[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    setError(null);
    getJson<Ticket[]>("/tickets")
      .then(setTickets)
      .catch((err: unknown) => {
        if (err instanceof ApiError && err.status === 401) {
          void signOut();
          return;
        }
        if (err instanceof ApiError && err.status === 409) {
          setError("workflow busy");
          return;
        }
        setError(err instanceof Error ? err.message : "request failed");
      });
  }, [signOut]);

  useEffect(() => {
    if (username) {
      load();
    }
  }, [load, username]);

  if (!ready) {
    return null;
  }
  if (!username) {
    return <Navigate to="/login" replace />;
  }

  return (
    <>
      <header className="site-header">
        <div className="nav">
          <BrandMark />
          <button type="button" className="btn btn-ghost" onClick={() => void signOut()}>
            Sign out
          </button>
        </div>
      </header>
      <main className="shell">
        <div className="page-head">
          <h1>Tickets</h1>
          <button type="button" className="btn btn-primary" onClick={load}>
            Refresh
          </button>
        </div>
        {error ? <p className="muted">{error}</p> : null}
        {tickets ? (
          <ul className="tickets">
            {tickets.map((ticket) => (
              <li key={ticket.id}>
                <span className="id">{ticket.id}</span>
                <span className="status">{ticket.status}</span>
              </li>
            ))}
          </ul>
        ) : null}
      </main>
    </>
  );
}
