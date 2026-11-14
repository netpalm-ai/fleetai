import { useCallback, useEffect, useRef, useState, type ChangeEvent, type DragEvent } from "react";
import { Link, Navigate } from "react-router-dom";
import { ApiError, getJson, request } from "../api/client";
import { BrandMark } from "../components/BrandMark";
import { useSession } from "../session";
import type { Job, Ticket } from "../types";

function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const value = String(reader.result ?? "");
      const comma = value.indexOf(",");
      resolve(comma >= 0 ? value.slice(comma + 1) : value);
    };
    reader.onerror = () => reject(new Error("Could not read the PDF."));
    reader.readAsDataURL(file);
  });
}

export function TicketsPage() {
  const { username, ready, signOut } = useSession();
  const [email, setEmail] = useState("");
  const [listText, setListText] = useState("");
  const [context, setContext] = useState("");
  const [pdfName, setPdfName] = useState<string | null>(null);
  const [pdfBase64, setPdfBase64] = useState<string | null>(null);
  const [listMode, setListMode] = useState<"paste" | "pdf">("paste");
  const [tickets, setTickets] = useState<Ticket[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [busy, setBusy] = useState(false);
  const poll = useRef<number | null>(null);

  const load = useCallback(() => {
    getJson<Ticket[]>("/tickets")
      .then(setTickets)
      .catch((err: unknown) => {
        if (err instanceof ApiError && err.status === 401) {
          void signOut();
          return;
        }
        if (err instanceof ApiError && err.status === 403) {
          setError("This account cannot use tickets.");
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

  useEffect(() => {
    return () => {
      if (poll.current != null) {
        window.clearInterval(poll.current);
      }
    };
  }, []);

  function stopPoll() {
    if (poll.current != null) {
      window.clearInterval(poll.current);
      poll.current = null;
    }
  }

  function watchJob(jobId: string) {
    stopPoll();
    const tick = () => {
      getJson<Job>("/jobs/" + jobId)
        .then((next) => {
          setJob(next);
          load();
          if (next.status === "done" || next.status === "error") {
            setBusy(false);
            stopPoll();
            if (next.status === "error") {
              setError(next.error || "resolve failed");
            }
          }
        })
        .catch((err: unknown) => {
          setBusy(false);
          stopPoll();
          setError(err instanceof Error ? err.message : "job poll failed");
        });
    };
    tick();
    poll.current = window.setInterval(tick, 2000);
  }

  async function acceptPdf(file: File) {
    if (!file.name.toLowerCase().endsWith(".pdf")) {
      setError("Upload a .pdf file.");
      return;
    }
    setError(null);
    setPdfName(file.name);
    setPdfBase64(await fileToBase64(file));
  }

  function onPdf(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (file) {
      void acceptPdf(file);
    }
  }

  function onDrop(event: DragEvent<HTMLLabelElement>) {
    event.preventDefault();
    const file = event.dataTransfer.files[0];
    if (file) {
      void acceptPdf(file);
    }
  }

  async function onResolve() {
    const list = listMode === "pdf" ? "" : listText;
    const encoded = listMode === "pdf" ? pdfBase64 : null;
    if (!email.trim() && !list.trim() && !encoded) {
      setError("Add an email or a ticket list.");
      return;
    }
    setError(null);
    setBusy(true);
    try {
      await request<void>("/tickets/inputs", {
        method: "POST",
        body: JSON.stringify({
          email,
          list_text: list,
          context,
          list_pdf_base64: encoded,
        }),
      });
      const started = await request<Job>("/execute", { method: "POST" });
      setJob(started);
      load();
      watchJob(started.id);
    } catch (err: unknown) {
      setBusy(false);
      if (err instanceof ApiError && err.status === 401) {
        void signOut();
        return;
      }
      setError(err instanceof Error ? err.message : "resolve failed");
    }
  }

  if (!ready) {
    return null;
  }
  if (!username) {
    return <Navigate to="/login" replace />;
  }

  const running = busy || job?.status === "running";
  const active = tickets?.find((ticket) => ticket.status === "verifying");

  return (
    <>
      <header className="site-header">
        <div className="nav nav-wide">
          <Link to="/">
            <BrandMark />
          </Link>
          <div className="nav-end">
            <span className="nav-user">{username}</span>
            <button type="button" className="btn btn-ghost" onClick={() => void signOut()}>
              Sign out
            </button>
          </div>
        </div>
      </header>
      <main className="shell shell-wide">
        <div className="page-head">
          <div>
            <p className="eyebrow">Workspace</p>
            <h1>Resolve tickets</h1>
          </div>
        </div>
        {error ? <p className="form-error studio-error">{error}</p> : null}
        {running ? (
          <p className="studio-live">
            {active ? "Solving " + active.id + (active.title ? " — " + active.title : "") : "Parsing and running the pipeline…"}
          </p>
        ) : null}

        <div className="studio">
          <section className="intake">
            <label className="field">
              Email
              <textarea
                name="email"
                rows={6}
                placeholder="Paste the evaluator email or defect notes."
                value={email}
                onChange={(event) => setEmail(event.target.value)}
              />
            </label>
            <div className="field">
              Ticket list
              <div className="seg" role="tablist" aria-label="Ticket list source">
                <button
                  type="button"
                  role="tab"
                  aria-selected={listMode === "paste"}
                  className={listMode === "paste" ? "seg-btn on" : "seg-btn"}
                  onClick={() => setListMode("paste")}
                >
                  Paste text
                </button>
                <button
                  type="button"
                  role="tab"
                  aria-selected={listMode === "pdf"}
                  className={listMode === "pdf" ? "seg-btn on" : "seg-btn"}
                  onClick={() => setListMode("pdf")}
                >
                  Upload PDF
                </button>
              </div>
              {listMode === "paste" ? (
                <textarea
                  name="list_text"
                  rows={10}
                  placeholder="Paste the ticket list as raw text."
                  value={listText}
                  onChange={(event) => setListText(event.target.value)}
                />
              ) : (
                <label className="drop" onDragOver={(event) => event.preventDefault()} onDrop={onDrop}>
                  <input type="file" accept="application/pdf,.pdf" onChange={onPdf} />
                  <span>{pdfName ?? "Drop or choose a .pdf"}</span>
                </label>
              )}
            </div>
            <label className="field">
              Project context
              <textarea
                name="context"
                rows={8}
                placeholder="Optional. Paste project.md or other product context."
                value={context}
                onChange={(event) => setContext(event.target.value)}
              />
            </label>
            <button type="button" className="btn btn-primary btn-block resolve-btn" disabled={running} onClick={() => void onResolve()}>
              {running ? "Resolving…" : "Resolve tickets"}
            </button>
          </section>

          <section className="board">
            <div className="board-head">
              <h2>Tickets</h2>
              <button type="button" className="btn btn-ghost" onClick={load}>
                Refresh
              </button>
            </div>
            {tickets == null && !error ? <p className="muted">Loading tickets…</p> : null}
            {tickets && tickets.length === 0 ? <p className="muted">No tickets yet. Resolve to parse a list.</p> : null}
            {tickets && tickets.length > 0 ? (
              <ul className="tickets">
                {tickets.map((ticket) => (
                  <li key={ticket.id} className={"ticket-row is-" + ticket.status}>
                    <div>
                      <span className="id">{ticket.id}</span>
                      {ticket.title ? <p className="ticket-title">{ticket.title}</p> : null}
                    </div>
                    <span className="status">{ticket.status}</span>
                  </li>
                ))}
              </ul>
            ) : null}
          </section>
        </div>
      </main>
    </>
  );
}
