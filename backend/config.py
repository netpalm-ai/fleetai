"""Paths and ticket workflow."""

from __future__ import annotations

import contextvars
import os
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

import pymupdf

import intakes

ROOT = Path(__file__).resolve().parent


def load_local_env() -> None:
    path = ROOT / ".env"
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = value.strip().strip('"').strip("'")


load_local_env()


def require_env(name: str) -> str:
    value = (os.getenv(name) or "").strip()
    if not value:
        raise RuntimeError("{0} is required".format(name))
    return value


def require_env_int(name: str) -> int:
    return int(require_env(name))


INTAKE_PDF_MAX = 50 * 1024 * 1024
INTAKE_TEXT_MAX = 512 * 1024
CONTEXT_PATH = ROOT / "codebase" / "code-context.md"
ENGINEERING_PATH = ROOT / "codebase" / "engineering.md"
VERSION = "0.1.0"
_user_locks: dict[UUID, threading.Lock] = {}
_user_locks_guard = threading.Lock()
_held = threading.local()
_jobs: dict[UUID, dict] = {}


class WorkflowBusy(RuntimeError):
    pass


_PDF_REJECT = ("/JavaScript", "/EmbeddedFiles", "/Launch", "/RichMedia")


def _require_pdf(pdf: bytes) -> None:
    if len(pdf) > INTAKE_PDF_MAX:
        raise RuntimeError("ticket list PDF is too large")
    if not pdf.startswith(b"%PDF"):
        raise RuntimeError("ticket list PDF is invalid")
    try:
        document = pymupdf.open(stream=pdf, filetype="pdf")
    except Exception as exc:
        raise RuntimeError("ticket list PDF is invalid") from exc
    try:
        if document.is_encrypted or document.needs_pass:
            raise RuntimeError("ticket list PDF is encrypted")
        if document.page_count < 1:
            raise RuntimeError("ticket list PDF is invalid")
        for xref in range(1, document.xref_length()):
            try:
                obj = document.xref_object(xref)
            except Exception:
                continue
            if any(token in obj for token in _PDF_REJECT):
                raise RuntimeError("ticket list PDF is invalid")
    finally:
        document.close()


def save_intake(
    email: str,
    list_text: str,
    context: str,
    pdf: bytes | None,
    user_id: UUID,
    session_id: UUID | None,
) -> None:
    email = (email or "").strip()
    list_text = (list_text or "").strip()
    context = (context or "").strip()
    if "\x00" in email or "\x00" in list_text or "\x00" in context:
        raise RuntimeError("intake text is invalid")
    if pdf is not None:
        _require_pdf(pdf)
    if len(email) > INTAKE_TEXT_MAX or len(list_text) > INTAKE_TEXT_MAX or len(context) > INTAKE_TEXT_MAX:
        raise RuntimeError("intake text is too large")
    if not email and not list_text and not pdf:
        raise RuntimeError("need an email or a ticket list")
    with workflow_lock(user_id, blocking=False):
        if email:
            intakes.put(user_id, session_id, "email_desc", "txt", (email + "\n").encode("utf-8"))
        else:
            intakes.deactivate(user_id, "email_desc")
        if pdf is not None:
            intakes.put(user_id, session_id, "ticket_list", "pdf", pdf)
        elif list_text:
            intakes.put(user_id, session_id, "ticket_list", "txt", (list_text + "\n").encode("utf-8"))
        else:
            intakes.deactivate(user_id, "ticket_list")
        if context:
            intakes.put(user_id, session_id, "project_context", "md", (context + "\n").encode("utf-8"))
        else:
            intakes.deactivate(user_id, "project_context")


def _user_lock(user_id: UUID) -> threading.Lock:
    with _user_locks_guard:
        return _user_locks.setdefault(user_id, threading.Lock())


def workflow_busy(user_id: UUID) -> bool:
    return _user_lock(user_id).locked()


@contextmanager
def workflow_lock(user_id: UUID, blocking: bool = True):
    held = getattr(_held, "depth", None)
    if held is None:
        held = _held.depth = {}
    if held.get(user_id):
        held[user_id] += 1
        try:
            yield
        finally:
            held[user_id] -= 1
        return
    lock = _user_lock(user_id)
    if not lock.acquire(blocking=blocking):
        raise WorkflowBusy("workflow busy")
    held[user_id] = 1
    try:
        yield
    finally:
        held[user_id] = 0
        lock.release()


def locked(fn):
    def wrapped(user_id: UUID, *args, **kwargs):
        with workflow_lock(user_id):
            return fn(user_id, *args, **kwargs)

    wrapped.__name__ = fn.__name__
    wrapped.__doc__ = fn.__doc__
    return wrapped

UNRESOLVED = "unresolved"
VERIFYING = "verifying"
COMPLETED = "completed"
FIXED = "fixed"
TICKET_STATES = (UNRESOLVED, VERIFYING, COMPLETED, FIXED)
IN_FLIGHT = (VERIFYING, COMPLETED, FIXED)
READY = "ready"
BLOCKED = "blocked"
FAILED = "failed"
_STATUS = {name.lower(): name for name in TICKET_STATES}
REQUIRED = ("title", "severity", "services", "context", "expected")
TECH_FIELDS = ("id", "title", "severity", "services", "context", "expected")
REPORT_CHARS = 4000
_checkout: contextvars.ContextVar[Checkout | None] = contextvars.ContextVar("github_checkout", default=None)


@dataclass(frozen=True)
class Checkout:
    root: Path
    token: str | None = None
    branch: str | None = None


def activate_checkout(checkout: Checkout) -> contextvars.Token:
    return _checkout.set(checkout)


def restore_checkout(token: contextvars.Token) -> None:
    _checkout.reset(token)


def active_checkout() -> Checkout | None:
    return _checkout.get()


def base_product_root() -> Path:
    root = Path(require_env("FLEETAI_PRODUCT_ROOT"))
    if not root.is_dir():
        raise RuntimeError("product root is missing: {0}".format(root))
    return root


def projects_root() -> Path:
    root = Path(require_env("FLEETAI_PROJECTS"))
    root.mkdir(parents=True, exist_ok=True)
    return root


def product_cwd() -> Path:
    current = active_checkout()
    if current is not None:
        return current.root
    return base_product_root()


def _read_required(path: Path, label: str) -> str:
    if not path.is_file():
        raise RuntimeError("missing {0}: {1}".format(label, path))
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise RuntimeError("{0} is empty: {1}".format(label, path))
    return text


def code_context() -> str:
    return _read_required(CONTEXT_PATH, "code context")


def engineering_standard() -> str:
    return _read_required(ENGINEERING_PATH, "engineering standard")


def agent_context() -> str:
    return "ENGINEERING STANDARD\n{0}\n\nCODE CONTEXT\n{1}".format(engineering_standard(), code_context())


def product_areas() -> str:
    text = code_context()
    start = text.find("## Repositories")
    if start < 0:
        return text
    rest = text[start:]
    nxt = rest.find("\n## ", 1)
    return (rest[:nxt] if nxt > 0 else rest).strip()


def _safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in value) or "ticket"


def tech_ticket(ticket: dict) -> dict:
    return {key: ticket[key] for key in TECH_FIELDS if key in ticket}


def normalize_status(value: object, default: str | None = UNRESOLVED) -> str | None:
    if value is None or value == "":
        return default
    found = _STATUS.get(str(value).strip().lower())
    if found or default is None:
        return found
    raise RuntimeError("ticket status must be unresolved, verifying, completed, or fixed: {0}".format(value))


def normalize_ticket(item: object) -> dict:
    if not isinstance(item, dict):
        raise RuntimeError("each ticket must be an object")
    missing = [name for name in REQUIRED if name not in item]
    if missing:
        raise RuntimeError("ticket missing fields: {0}".format(", ".join(missing)))
    ticket = dict(item)
    ticket["id"] = str(item.get("id") or "").strip() or _safe_name(str(item.get("title") or ""))
    if not ticket["id"] or ticket["id"] == "ticket":
        raise RuntimeError("ticket id is empty")
    ticket["kind"] = "recurrent" if str(item.get("kind") or "").strip().lower() == "recurrent" else "new"
    services = item.get("services") or []
    if not isinstance(services, list):
        raise RuntimeError("ticket {0}: services must be a list".format(ticket["id"]))
    ticket["services"] = [str(service).strip() for service in services if str(service).strip()]
    repos = item.get("repos")
    if repos is None:
        ticket["repos"] = []
    elif not isinstance(repos, list):
        raise RuntimeError("ticket {0}: repos must be a list".format(ticket["id"]))
    raw = ticket.get("status")
    report = ticket.get("report_status")
    if raw and normalize_status(raw, default=None) is None:
        report = report or raw
        raw = ticket.get("state")
    ticket["report_status"] = str(report or "").strip()
    ticket["status"] = normalize_status(raw if raw is not None else ticket.get("state"))
    ticket.pop("state", None)
    return ticket


def normalize_tickets(raw: object) -> list[dict]:
    if not isinstance(raw, list):
        raise RuntimeError("parser output must be a JSON array")
    tickets = []
    seen: set[str] = set()
    for item in raw:
        ticket = normalize_ticket(item)
        if ticket["id"] in seen:
            raise RuntimeError("duplicate ticket id: {0}".format(ticket["id"]))
        seen.add(ticket["id"])
        tickets.append(ticket)
    return tickets


def last_verdict(text: str | None) -> str | None:
    if not text:
        return None
    allowed = {
        "verdict: fixed": FIXED,
        "verdict: failed": FAILED,
        "verdict: ready": READY,
        "verdict: blocked": BLOCKED,
    }
    for line in reversed(text.strip().splitlines()):
        found = allowed.get(line.strip().strip("*").strip("`").lower())
        if found:
            return found
    return None



def changed_files(report: str | None) -> list[str]:
    lines: list[str] = []
    collecting = False
    for raw in (report or "").splitlines():
        line = raw.strip()
        upper = line.upper()
        if upper.startswith("CHANGED FILES:"):
            collecting = True
            rest = line.split(":", 1)[1].strip()
            if rest:
                lines.append(rest)
            continue
        if not collecting:
            continue
        if upper.startswith("VERDICT:") or (
            ":" in line and line.split(":", 1)[0].replace(" ", "").isalpha() and line.split(":", 1)[0].isupper()
        ):
            break
        if line:
            lines.append(line)
    return lines


def push_ticket(ticket_id: str, report: str | None) -> None:
    import subprocess

    import connections

    root = product_cwd()
    checkout = active_checkout()
    token = checkout.token if checkout else None
    target = checkout.branch if checkout else None
    by_repo: dict[str, list[str]] = {}
    for entry in changed_files(report):
        name, sep, rel = entry.partition("/")
        path = Path(rel if sep else entry)
        if path.is_absolute() or ".." in path.parts or name in {".", ".."}:
            raise RuntimeError("changed file is not under a product git repo: {0}".format(entry))
        if sep and (root / name / ".git").exists():
            by_repo.setdefault(name, []).append(rel)
        elif (root / ".git").exists():
            by_repo.setdefault(".", []).append(entry)
        else:
            raise RuntimeError("changed file is not under a product git repo: {0}".format(entry))
    if not by_repo:
        raise RuntimeError("ticket {0} has no CHANGED FILES to commit".format(ticket_id))
    for repo, paths in sorted(by_repo.items()):
        cwd = root if repo == "." else root / repo
        unique = sorted(set(paths))
        connections.github.git(cwd, token, "add", "--", *unique)
        staged = subprocess.run(
            ["git", "diff", "--cached", "--name-only"], cwd=cwd, check=True, capture_output=True, text=True
        ).stdout.splitlines()
        if staged:
            connections.github.git(cwd, token, "commit", "-m", "fleetai: {0}".format(ticket_id))
        elif token is None:
            raise RuntimeError("nothing staged in {0} for ticket {1}".format(cwd.name, ticket_id))
        if target:
            connections.github.git(cwd, token, "push", "origin", "HEAD:{0}".format(target))
            branch = target
        else:
            branch = subprocess.run(
                ["git", "branch", "--show-current"], cwd=cwd, check=True, capture_output=True, text=True
            ).stdout.strip()
            if not branch:
                raise RuntimeError("detached HEAD in {0}; stay on a branch to push".format(cwd.name))
            connections.github.git(cwd, None, "push", "origin", "HEAD")
        print("{0}\tpushed\t{1}\t{2}".format(ticket_id, cwd.name, branch), flush=True)


def clip_report(text: str | None) -> str:
    report = (text or "").strip()
    if len(report) <= REPORT_CHARS:
        return report
    return "...\n" + report[-REPORT_CHARS:].split("\n", 1)[-1].strip()


def solved_prompt(tickets: dict[str, dict]) -> str:
    if not tickets:
        return "(none)"
    return "\n".join(
        "- {0} | {1} | {2}".format(ticket["id"], ticket.get("kind") or "", ticket.get("title") or "")
        for ticket in tickets.values()
    )


def _norm(value: object) -> str:
    return " ".join(str(value or "").split()).casefold()


def is_reopened(incoming: dict, solved: dict) -> bool:
    if incoming.get("kind") != "recurrent":
        return False
    return any(
        _norm(incoming.get(name)) != _norm(solved.get(name))
        for name in ("context", "expected")
    )


def apply_workflow(tickets: list[dict], existing: list[dict], archived: dict[str, dict]) -> list[dict]:
    previous = {item["id"]: item for item in existing}
    seen: set[str] = set()
    merged: list[dict] = []
    for ticket in tickets:
        solved = archived.get(ticket["id"])
        if solved is not None:
            seen.add(ticket["id"])
            if not is_reopened(ticket, solved):
                continue
            if not ticket.get("repos") and solved.get("repos"):
                ticket["repos"] = solved["repos"]
            ticket["status"] = UNRESOLVED
            merged.append(ticket)
            continue
        prior = previous.get(ticket["id"])
        if prior and prior.get("status") in IN_FLIGHT:
            kept = dict(prior)
            if ticket.get("report_status"):
                kept["report_status"] = ticket["report_status"]
            merged.append(kept)
        else:
            if prior and not ticket.get("repos") and prior.get("repos"):
                ticket["repos"] = prior["repos"]
            ticket["status"] = UNRESOLVED
            merged.append(ticket)
        seen.add(ticket["id"])
    merged.extend(
        prior
        for prior in existing
        if prior["id"] not in seen and prior["id"] not in archived and prior.get("status") in IN_FLIGHT
    )
    return merged


def require_ticket(user_id: UUID, ticket_id: str) -> dict:
    ticket = intakes.find_ticket(user_id, ticket_id)
    if ticket is None:
        raise SystemExit("ticket not found: {0}".format(ticket_id))
    return ticket


def new_job(user_id: UUID, kind: str, ticket_id: str | None = None) -> dict:
    job = {
        "id": str(uuid.uuid4()),
        "kind": kind,
        "status": "running",
        "ticket_id": ticket_id,
        "run_id": None,
        "error": None,
    }
    _jobs[user_id] = job
    return job


def load_job(user_id: UUID, job_id: str) -> dict | None:
    job = _jobs.get(user_id)
    if job is None or job["id"] != job_id:
        return None
    return dict(job)


def read_run_log(user_id: UUID, ticket_id: str, run_id: str) -> str | None:
    run = intakes.get_run(user_id, ticket_id, run_id)
    if run is None:
        return None
    return "# {0} {1}\n\n- verdict: {2}\n- run: {3}\n\n## Prompt\n{4}\n\n## Result\n{5}\n".format(
        ticket_id, run["kind"], run["verdict"] or "none", run["run_id"], run["prompt"], run["result"]
    )


def run_step(user_id: UUID, ticket_id: str, want: str, kind: str, make_prompt, next_status: dict[str, str], fallback: str = "no verdict") -> None:
    ticket = require_ticket(user_id, ticket_id)
    if ticket["status"] != want:
        print("{0}\tskipped\t{1}".format(ticket_id, ticket["status"]))
        return
    prompt = make_prompt(ticket, agent_context())
    from llm import cursor
    result = cursor.run(prompt)
    if result.result:
        print(result.result)
    verdict = last_verdict(result.result)
    intakes.add_run(user_id, ticket_id, result.id or kind, kind, verdict, prompt, result.result)
    status = next_status.get(verdict)
    if status:
        intakes.set_ticket_status(user_id, ticket_id, status)
        if verdict == FAILED:
            print("{0}\t{1}\t{2}".format(ticket_id, status, FAILED))
        else:
            print("{0}\t{1}".format(ticket_id, status))
        return
    print("{0}\t{1}\t{2}".format(ticket_id, want, verdict or fallback))
