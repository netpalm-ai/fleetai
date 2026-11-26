import { useCallback, useEffect, useRef, useState, type ChangeEvent, type DragEvent } from "react";
import { ApiError, getJson, request, requestError } from "../api/client";
import { AppShell } from "../components/AppShell";
import { useSession } from "../session";
import type { Job, Ticket } from "../types";

function handlingId(tickets: Ticket[]): string | null {
  const unresolved = tickets.find((ticket) => ticket.status === "unresolved");
  if (unresolved) {
    return unresolved.id;
  }
  const verifying = tickets.find((ticket) => ticket.status === "verifying");
  return verifying ? verifying.id : null;
}

function liveStatus(ticket: Ticket, running: boolean, activeId: string | null): string {
  if (running && ticket.id === activeId) {
    return ticket.status === "verifying" ? "Verifying…" : "Solving…";
  }
  if (ticket.status === "verifying") {
    return "Verifying";
  }
  if (ticket.status === "fixed") {
    return "Fixed";
  }
  if (ticket.status === "completed") {
    return "Completed";
  }
  if (running && ticket.status === "unresolved") {
    return "Queued";
  }
  if (ticket.status === "unresolved" && ticket.latest_verdict === "blocked") {
    return "Blocked";
  }
  if (ticket.status === "unresolved" && ticket.latest_verdict === "failed") {
    return "Failed";
  }
  return "Open";
}

function ticketBlurb(ticket: Ticket): string {
  return (ticket.context || "").trim().replace(/\s+/g, " ");
}

function stamp(value: string | null | undefined): string | null {
  if (!value) {
    return null;
  }
  const when = new Date(value);
  if (Number.isNaN(when.getTime())) {
    return value;
  }
  return when.toLocaleString();
}

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
  const { username } = useSession();
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
  const [openId, setOpenId] = useState<string | null>(null);
  const [report, setReport] = useState<string | null>(null);
  const [reportBusy, setReportBusy] = useState(false);
  const poll = useRef<number | null>(null);

  const load = useCallback(() => {
    getJson<Ticket[]>("/tickets")
      .then(setTickets)
      .catch((err: unknown) => {
        if (err instanceof ApiError && err.status === 403) {
          setError("This account cannot use tickets.");
          return;
        }
        if (err instanceof ApiError && err.status === 409) {
          setError("workflow busy");
          return;
        }
        const message = requestError(err, "request failed");
        if (message) {
          setError(message);
        }
      });
  }, []);

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
          const message = requestError(err, "job poll failed");
          if (message) {
            setError(message);
          }
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
    event.target.value = "";
    event.target.blur();
  }

  function onPdfDragOver(event: DragEvent) {
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
  }

  function onPdfDrop(event: DragEvent) {
    event.preventDefault();
    setListMode("pdf");
    const file = event.dataTransfer.files[0];
    if (file) {
      void acceptPdf(file);
    }
  }

  async function onComplete(ticketId: string) {
    setError(null);
    try {
      await request<Ticket>("/tickets/" + ticketId + "/complete", { method: "POST" });
      load();
    } catch (err: unknown) {
      const message = requestError(err, "complete failed");
      if (message) {
        setError(message);
      }
    }
  }

  async function onShowReport(ticket: Ticket) {
    if (!ticket.latest_run_id) {
      setError("No run report yet.");
      return;
    }
    if (openId === ticket.id) {
      setOpenId(null);
      setReport(null);
      return;
    }
    setError(null);
    setReportBusy(true);
    setOpenId(ticket.id);
    try {
      const body = await getJson<{ text: string }>(
        "/tickets/" + ticket.id + "/runs/" + ticket.latest_run_id,
      );
      setReport(body.text);
    } catch (err: unknown) {
      setOpenId(null);
      setReport(null);
      const message = requestError(err, "Could not load the report.");
      if (message) {
        setError(message);
      }
    } finally {
      setReportBusy(false);
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
      const message = requestError(err, "resolve failed");
      if (message) {
        setError(message);
      }
    }
  }

  const running = busy || job?.status === "running";
  const activeId = tickets && running ? handlingId(tickets) : null;

  return (
    <AppShell>
      <main className="shell shell-app">
        <div className="page-head">
          <div>
            <p className="eyebrow">Workspace</p>
            <h1>Resolve tickets</h1>
          </div>
        </div>
        {error ? (
          <p className="form-error studio-error" role="alert">
            {error}
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
                <label
                  role="tab"
                  aria-selected={listMode === "pdf"}
                  className={listMode === "pdf" ? "seg-btn on" : "seg-btn"}
                  onClick={() => setListMode("pdf")}
                  onDragOver={onPdfDragOver}
                  onDrop={onPdfDrop}
                >
                  <input
                    className="pdf-input"
                    type="file"
                    accept="application/pdf,.pdf"
                    tabIndex={-1}
                    aria-hidden="true"
                    onChange={onPdf}
                  />
                  Upload or Drop PDF here
                </label>
              </div>
              {listMode === "paste" ? (
                <textarea
                  name="list_text"
                  rows={10}
                  placeholder="Paste the ticket list as raw text."
                  value={listText}
                  onChange={(event) => setListText(event.target.value)}
                />
              ) : pdfName ? (
                <p className="pdf-name">{pdfName}</p>
              ) : null}
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
            </div>
            {tickets == null && !error ? <p className="muted">Loading tickets…</p> : null}
            {tickets && tickets.length === 0 ? (
              <p className="muted">
                {running ? "Parsing the list…" : "No tickets yet. Resolve to parse a list."}
              </p>
            ) : null}
            {tickets && tickets.length > 0 ? (
              <ul className="tickets">
                {tickets.map((ticket) => {
                  const blurb = ticketBlurb(ticket);
                  const active = ticket.id === activeId;
                  const handled = stamp(ticket.handled_at);
                  const outcome = liveStatus(ticket, running, activeId);
                  return (
                    <li
                      key={ticket.id}
                      className={
                        "ticket-row is-" +
                        ticket.status +
                        (active ? " is-active" : "") +
                        (ticket.latest_verdict ? " is-" + ticket.latest_verdict : "")
                      }
                    >
                      <p className="ticket-line">
                        <span className="id">{ticket.id}</span>
                        <span className="ticket-sep">—</span>
                        <span className="ticket-title">{ticket.title || "Untitled"}</span>
                        <span className="status">{outcome}</span>
                      </p>
                      {blurb ? <p className="ticket-desc">{blurb}</p> : null}
                      {handled ? <p className="ticket-meta">Handled {handled}</p> : null}
                      <div className="ticket-actions">
                        {ticket.status === "verifying" && !running ? (
                          <button
                            type="button"
                            className="btn btn-primary"
                            onClick={() => void onComplete(ticket.id)}
                          >
                            Mark completed
                          </button>
                        ) : null}
                        {ticket.latest_run_id ? (
                          <button
                            type="button"
                            className="btn"
                            onClick={() => void onShowReport(ticket)}
                          >
                            {openId === ticket.id ? "Hide report" : "Show report"}
                          </button>
                        ) : null}
                      </div>
                      {openId === ticket.id ? (
                        <pre className="ticket-report">{reportBusy ? "Loading…" : report || "No report."}</pre>
                      ) : null}
                    </li>
                  );
                })}
              </ul>
            ) : null}
          </section>
        </div>
      </main>
    </AppShell>
  );
}
