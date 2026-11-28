import { useCallback, useEffect, useRef, useState, type ChangeEvent, type DragEvent } from "react";
import { useSearchParams } from "react-router-dom";
import { ApiError, getJson, request, requestError } from "../api/client";
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
    reader.onerror = () => reject(new Error("Could not read the file."));
    reader.readAsDataURL(file);
  });
}

const INTAKE_MAX_BYTES = 50 * 1024 * 1024;
const IMAGE_MAX_BYTES = 5 * 1024 * 1024;
const IMAGE_MAX_COUNT = 8;

function imageKind(file: File): "png" | "jpeg" | "webp" | null {
  const name = file.name.toLowerCase();
  const type = file.type.toLowerCase();
  if (type === "image/png" || name.endsWith(".png")) {
    return "png";
  }
  if (type === "image/jpeg" || name.endsWith(".jpeg") || name.endsWith(".jpg")) {
    return "jpeg";
  }
  if (type === "image/webp" || name.endsWith(".webp")) {
    return "webp";
  }
  return null;
}

export function WorkspacePage() {
  const { username, userType } = useSession();
  const [params, setParams] = useSearchParams();
  const projectId = params.get("project");
  const [email, setEmail] = useState("");
  const [listText, setListText] = useState("");
  const [context, setContext] = useState("");
  const [pdfName, setPdfName] = useState<string | null>(null);
  const [pdfBase64, setPdfBase64] = useState<string | null>(null);
  const [pdfBytes, setPdfBytes] = useState(0);
  const [images, setImages] = useState<{ name: string; data: string; bytes: number }[]>([]);
  const [listMode, setListMode] = useState<"paste" | "pdf">("paste");
  const [tickets, setTickets] = useState<Ticket[] | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [runIds, setRunIds] = useState<string[]>([]);
  const listedIds = useRef<Set<string> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [instruction, setInstruction] = useState("");
  const [improving, setImproving] = useState(false);
  const [improveError, setImproveError] = useState<string | null>(null);
  const improvePoll = useRef<number | null>(null);
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
          setError("This account cannot use the workspace.");
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
        const first = rows[0];
        if (!first) {
          setTickets([]);
          return;
        }
        setParams((current) => {
          const id = current.get("project");
          if (id && rows.some((row) => row.id === id)) {
            return current;
          }
          const next = new URLSearchParams(current);
          next.set("project", first.id);
          return next;
        }, { replace: true });
      })
      .catch((err: unknown) => {
        const message = requestError(err, "Something went wrong. Try again.");
        if (message) {
          setError(message);
        }
      });
  }, [username, setParams]);

  useEffect(() => {
    setTickets(null);
    setSelected([]);
    listedIds.current = null;
    setOpenId(null);
    setReport(null);
  }, [projectId]);

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
      if (improvePoll.current != null) {
        window.clearInterval(improvePoll.current);
      }
    };
  }, []);

  function runInstruction() {
    const text = instruction.trim();
    if (!text || improving) {
      return;
    }
    setImproving(true);
    setImproveError(null);
    request<Job>("/self-improve", { method: "POST", body: JSON.stringify({ instruction: text }) })
      .then((started) => {
        if (improvePoll.current != null) {
          window.clearInterval(improvePoll.current);
        }
        improvePoll.current = window.setInterval(() => {
          getJson<Job>("/jobs/" + started.id)
            .then((next) => {
              if (next.status !== "done" && next.status !== "error") {
                return;
              }
              if (improvePoll.current != null) {
                window.clearInterval(improvePoll.current);
                improvePoll.current = null;
              }
              setImproving(false);
              if (next.status === "error") {
                setImproveError(next.error || "The run failed.");
              }
            })
            .catch((err: unknown) => {
              if (improvePoll.current != null) {
                window.clearInterval(improvePoll.current);
                improvePoll.current = null;
              }
              setImproving(false);
              setImproveError(requestError(err, "The run failed.") || "The run failed.");
            });
        }, 2000);
      })
      .catch((err: unknown) => {
        setImproving(false);
        if (err instanceof ApiError && err.status === 403) {
          setImproveError("This account cannot run an improvement.");
          return;
        }
        if (err instanceof ApiError && err.status === 409) {
          setImproveError("A run is already in progress.");
          return;
        }
        setImproveError(requestError(err, "Could not start the run.") || "Could not start the run.");
      });
  }

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
            setError(next.error || "Could not resolve. Try again.");
          }
        })
        .catch((err: unknown) => {
          setBusy(false);
          setRunIds([]);
          stopPoll();
          const message = requestError(err, "Could not resolve. Try again.");
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
    const imageBytes = images.reduce((sum, image) => sum + image.bytes, 0);
    if (file.size + imageBytes > INTAKE_MAX_BYTES) {
      setError("The upload must stay within 50 MB.");
      return;
    }
    setError(null);
    setPdfName(file.name);
    setPdfBytes(file.size);
    setPdfBase64(await fileToBase64(file));
  }

  async function onImages(event: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.target.files ?? []);
    event.target.value = "";
    if (files.length === 0) {
      return;
    }
    if (files.length > IMAGE_MAX_COUNT) {
      setError("Attach at most 8 images.");
      return;
    }
    const pdfSize = listMode === "pdf" ? pdfBytes : 0;
    let total = pdfSize;
    const next: { name: string; data: string; bytes: number }[] = [];
    for (const file of files) {
      if (!imageKind(file)) {
        setError("Upload png, jpeg, or webp images.");
        return;
      }
      if (file.size > IMAGE_MAX_BYTES) {
        setError("Each image must be at most 5 MB.");
        return;
      }
      total += file.size;
      if (total > INTAKE_MAX_BYTES) {
        setError("The upload must stay within 50 MB.");
        return;
      }
      next.push({ name: file.name, data: await fileToBase64(file), bytes: file.size });
    }
    setError(null);
    setImages(next);
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
      const message = requestError(err, "Could not mark it completed.");
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
    const imageData = images.map((image) => image.data);
    setError(null);
    setBusy(true);
    setRunIds(ids);
    try {
      if (saveInputs && (email.trim() || list.trim() || encoded || imageData.length > 0)) {
        await request<void>("/tickets/inputs", {
          method: "POST",
          body: JSON.stringify({
            email,
            list_text: list,
            context,
            list_pdf_base64: encoded,
            list_images_base64: imageData,
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
      const message = requestError(err, "Could not resolve. Try again.");
      if (message) {
        setError(message);
      }
    }
  }

  const running = busy || job?.status === "running";
  const bulk = running && !job?.ticket_id;
  const activeId = running ? job?.ticket_id || null : null;

  return (
      <main className="shell shell-app">
        <div className="page-head">
          <div>
            <h1>Workspace</h1>
          </div>
        </div>
        {error ? (
          <p className="form-error studio-error" role="alert">
            {error}
          </p>
        ) : null}

        {userType === "admin" ? (
          <section className="intake improve">
            <label className="field">
              Instruction
              <textarea
                name="instruction"
                rows={4}
                placeholder="Tell FleetAI what to improve."
                value={instruction}
                onChange={(event) => setInstruction(event.target.value)}
              />
            </label>
            <button
              type="button"
              className="btn btn-primary"
              disabled={improving || instruction.trim() === ""}
              onClick={runInstruction}
            >
              {improving ? "Running…" : "Run"}
            </button>
            {improveError ? (
              <p className="form-error" role="alert">
                {improveError}
              </p>
            ) : null}
          </section>
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
              <label htmlFor="work-list">List</label>
              <div className="seg" role="tablist" aria-label="List source">
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
                  id="work-list"
                  name="list_text"
                  rows={10}
                  placeholder="Paste the list as raw text."
                  value={listText}
                  onChange={(event) => setListText(event.target.value)}
                />
              ) : pdfName ? (
                <p className="pdf-name">{pdfName}</p>
              ) : null}
            </div>
            <label className="field">
              Images
              <input
                type="file"
                accept="image/png,image/jpeg,image/webp,.png,.jpeg,.jpg,.webp"
                multiple
                onChange={(event) => void onImages(event)}
              />
              {images.length > 0 ? (
                <p className="pdf-name">{images.map((image) => image.name).join(", ")}</p>
              ) : null}
            </label>
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
              onClick={() => void startResolve(openTicketIds(tickets), "Nothing to resolve.", true)}
            >
              {running ? "Resolving…" : "Resolve"}
            </button>
          </section>

          <section className="board">
            {tickets == null && projectId && !error ? <p className="muted">Loading…</p> : null}
            {tickets && tickets.length === 0 ? (
              <p className="muted">
                {running ? "Reading the list…" : "Nothing here yet. Add a list, then choose Resolve."}
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
                            <span>Resolve</span>
                          </label>
                        ) : null}
                        {ticket.status === "verifying" && !running ? (
                          <button
                            type="button"
                            className="btn btn-ghost"
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
                className="btn btn-ghost btn-block resolve-btn"
                disabled={running}
                onClick={() => void startResolve(selected, "Select one.", false)}
              >
                {running ? "Resolving…" : "Resolve only"}
              </button>
            ) : null}
          </section>
        </div>
      </main>
  );
}
