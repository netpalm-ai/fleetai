import { useCallback, useEffect, useRef, useState, type ChangeEvent, type DragEvent } from "react";
import { ApiError, getJson, request, requestError } from "../api/client";
import { AppShell } from "../components/AppShell";
import { useSession } from "../session";
import type { Job, Project, Ticket } from "../types";

function liveStatus(ticket: Ticket, running: boolean, bulk: boolean, activeId: string | null, chosen: boolean): string {
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
  if (bulk && chosen && ticket.status === "unresolved") {
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

function openTicketIds(rows: Ticket[] | null): string[] {
  return (rows ?? [])
    .filter((row) => row.status === "unresolved" || row.status === "verifying")
    .map((row) => row.id);
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
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [projectId, setProjectId] = useState<string | null>(null);
  const [tickets, setTickets] = useState<Ticket[] | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [runIds, setRunIds] = useState<string[]>([]);
  const listedIds = useRef<Set<string> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [busy, setBusy] = useState(false);
  const [openId, setOpenId] = useState<string | null>(null);
  const [report, setReport] = useState<string | null>(null);
  const [reportBusy, setReportBusy] = useState(false);
  const poll = useRef<number | null>(null);

  const load = useCallback(() => {
    if (projectId === null) {
      return;
    }
    const path = projectId ? `/tickets?project_id=${encodeURIComponent(projectId)}` : "/tickets";
    getJson<Ticket[]>(path)
      .then((rows) => {
        const previous = listedIds.current;
        const openIds = openTicketIds(rows);
        listedIds.current = new Set(rows.map((row) => row.id));
        setTickets(rows);
        setSelected((current) => {
          if (previous == null) {
            return openIds;
          }
          const open = new Set(openIds);
          const kept = current.filter((id) => open.has(id));
          const added = openIds.filter((id) => !previous.has(id) && !kept.includes(id));
          return kept.concat(added);
        });
      })
      .catch((err: unknown) => {
        if (err instanceof ApiError && err.status === 403) {
          setError("This account cannot use tickets.");
          return;
        }
        if (err instanceof ApiError && err.status === 409) {
          setError("A run is already in progress.");
          return;
        }
        const message = requestError(err, "Something went wrong. Try again.");
        if (message) {
          setError(message);
        }
      });
  }, [projectId]);

  useEffect(() => {
    if (!username) {
      return;
    }
    getJson<Project[]>("/projects")
      .then((rows) => {
        setProjects(rows);
        setProjectId((current) => {
          if (current && rows.some((row) => row.id === current)) {
            return current;
          }
          return rows[0]?.id ?? "";
        });
      })
      .catch((err: unknown) => {
        const message = requestError(err, "Something went wrong. Try again.");
        if (message) {
          setError(message);
        }
      });
  }, [username]);

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
          if (next.status !== "done" && next.status !== "error") {
            return;
          }
          stopPoll();
          setBusy(false);
          setRunIds([]);
          if (next.status === "error") {
            setError(next.error || "Could not resolve tickets. Try again.");
          }
        })
        .catch((err: unknown) => {
          setBusy(false);
          setRunIds([]);
          stopPoll();
          const message = requestError(err, "Could not resolve tickets. Try again.");
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

  function toggleSelected(ticketId: string, checked: boolean) {
    setSelected((current) =>
      checked ? current.concat(ticketId) : current.filter((id) => id !== ticketId),
    );
  }

  async function startResolve(ids: string[], emptyMessage: string, saveInputs: boolean) {
    if (ids.length === 0) {
      setError(emptyMessage);
      return;
    }
    const list = listMode === "pdf" ? "" : listText;
    const encoded = listMode === "pdf" ? pdfBase64 : null;
    setError(null);
    setBusy(true);
    setRunIds(ids);
    try {
      if (saveInputs && (email.trim() || list.trim() || encoded)) {
        await request<void>("/tickets/inputs", {
          method: "POST",
          body: JSON.stringify({
            email,
            list_text: list,
            context,
            list_pdf_base64: encoded,
          }),
        });
      }
      const started = await request<Job>("/execute", {
        method: "POST",
        body: JSON.stringify({ ticket_ids: ids }),
      });
      setJob(started);
      load();
      watchJob(started.id);
    } catch (err: unknown) {
      setBusy(false);
      setRunIds([]);
      const message = requestError(err, "Could not resolve tickets. Try again.");
      if (message) {
        setError(message);
      }
    }
  }

  const running = busy || job?.status === "running";
  const bulk = running && !job?.ticket_id;
  const activeId = running ? job?.ticket_id || null : null;

  function selectProject(id: string) {
    if (id === projectId) {
      return;
    }
    setProjectId(id);
    setTickets(null);
    setSelected([]);
    listedIds.current = null;
    setOpenId(null);
    setReport(null);
  }

  return (
    <AppShell>
      <main className="shell shell-app">
        <div className="page-head">
          <div>
            <p className="eyebrow">Workspace</p>
            <h1>Resolve tickets</h1>
          </div>
          {projects && projects.length > 0 ? (
            <div className="seg" role="tablist" aria-label="Project">
              {projects.map((project) => (
                <button
                  key={project.id}
                  type="button"
                  role="tab"
                  aria-selected={project.id === projectId}
                  className={project.id === projectId ? "seg-btn on" : "seg-btn"}
                  onClick={() => selectProject(project.id)}
                >
                  {project.product_name || project.name}
                </button>
              ))}
            </div>
          ) : null}
        </div>
        {error ? (
          <p className="form-error studio-error" role="alert">
            {error}
          </p>
        ) : null}

        <div className="studio">
          <section className="intake">
            <label className="field">
              Notes
              <textarea
                name="email"
                rows={6}
                placeholder="Paste an email or defect notes."
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
                  Upload PDF
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
            <button
              type="button"
              className="btn btn-primary btn-block resolve-btn"
              disabled={running}
              onClick={() => void startResolve(openTicketIds(tickets), "No tickets to resolve.", true)}
            >
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
                {running ? "Reading the list…" : "No tickets yet. Add a list, then choose Resolve."}
              </p>
            ) : null}
            {tickets && tickets.length > 0 ? (
              <ul className="tickets">
                {tickets.map((ticket) => {
                  const blurb = ticketBlurb(ticket);
                  const active = ticket.id === activeId;
                  const handled = stamp(ticket.handled_at);
                  const outcome = liveStatus(ticket, running, bulk, activeId, runIds.includes(ticket.id));
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
                        {ticket.status === "unresolved" || ticket.status === "verifying" ? (
                          <label className="accept">
                            <input
                              type="checkbox"
                              aria-label={"Resolve " + ticket.id}
                              checked={selected.includes(ticket.id)}
                              disabled={running}
                              onChange={(event) => toggleSelected(ticket.id, event.target.checked)}
                            />
                          </label>
                        ) : null}
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
            {tickets != null ? (
              <button
                type="button"
                className="btn btn-primary btn-block resolve-btn"
                disabled={running}
                onClick={() => void startResolve(selected, "Select a ticket.", false)}
              >
                {running ? "Resolving…" : "Resolve only"}
              </button>
            ) : null}
          </section>
        </div>
      </main>
    </AppShell>
  );
}
