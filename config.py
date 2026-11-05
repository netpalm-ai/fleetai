"""Paths, ticket workflow, and the Cursor call."""

from __future__ import annotations

import json
import os
from pathlib import Path

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

TICKETS_DIR = ROOT / "tickets"
PDF_PATH = TICKETS_DIR / "list.pdf"
EMAIL_PATH = TICKETS_DIR / "email.desc.txt"
TICKETS_PATH = TICKETS_DIR / "unsolved_tickets.json"
SOLVED_DIR = TICKETS_DIR / "solved"
RUNS_DIR = TICKETS_DIR / "runs"
CONTEXT_PATH = ROOT / "codebase" / "code-context.md"

UNRESOLVED = "unresolved"
VERIFYING = "verifying"
COMPLETED = "completed"
FIXED = "fixed"
TICKET_STATES = (UNRESOLVED, VERIFYING, COMPLETED, FIXED)
IN_FLIGHT = (VERIFYING, COMPLETED, FIXED)
SOLVED = (FIXED, COMPLETED)
READY = "ready"
BLOCKED = "blocked"
FAILED = "failed"
_STATUS = {name.lower(): name for name in TICKET_STATES}
REQUIRED = ("title", "severity", "services", "context", "expected")
TECH_FIELDS = ("id", "title", "severity", "services", "context", "expected")
CURSOR_MODEL = (os.getenv("FLEETAI_CURSOR_MODEL") or "grok-4.6").strip()


def product_cwd() -> Path:
    raw = (os.getenv("FLEETAI_PRODUCT_ROOT") or "").strip()
    if not raw:
        raise RuntimeError("FLEETAI_PRODUCT_ROOT is required")
    root = Path(raw)
    if not root.is_dir():
        raise RuntimeError("product root is missing: {0}".format(root))
    return root


def code_context() -> str:
    if not CONTEXT_PATH.is_file():
        raise RuntimeError("missing code context: {0}".format(CONTEXT_PATH))
    text = CONTEXT_PATH.read_text(encoding="utf-8").strip()
    if not text:
        raise RuntimeError("code context is empty: {0}".format(CONTEXT_PATH))
    return text


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


def ticket_where(ticket: dict) -> str:
    repos = ", ".join(
        repo.get("name", "") for repo in ticket.get("repos") or [] if isinstance(repo, dict)
    )
    return repos or ", ".join(ticket.get("services") or [])


def run_cursor(prompt: str):
    api_key = (os.getenv("CURSOR_API_KEY") or "").strip()
    if not api_key:
        raise SystemExit("CURSOR_API_KEY is required")
    from cursor_sdk import Agent, AgentOptions, LocalAgentOptions, ModelParameterValue, ModelSelection

    model = CURSOR_MODEL
    if CURSOR_MODEL.startswith("grok-"):
        model = ModelSelection(
            id=CURSOR_MODEL,
            params=[
                ModelParameterValue(id="reasoning", value="high"),
                ModelParameterValue(id="fast", value="true"),
            ],
        )
    result = Agent.prompt(
        prompt,
        AgentOptions(api_key=api_key, model=model, local=LocalAgentOptions(cwd=str(product_cwd()))),
    )
    if result.status == "error":
        raise RuntimeError("run failed: {0}".format(result.id))
    return result


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


def load_solved(solved_dir: Path = SOLVED_DIR) -> dict[str, dict]:
    if not solved_dir.is_dir():
        return {}
    tickets = {}
    for path in sorted(solved_dir.glob("*.json")):
        ticket = json.loads(path.read_text(encoding="utf-8"))
        tickets[str(ticket["id"])] = ticket
    return tickets


def solved_prompt(solved_dir: Path = SOLVED_DIR) -> str:
    tickets = load_solved(solved_dir)
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


def apply_workflow(tickets: list[dict], existing: list[dict], solved_dir: Path = SOLVED_DIR) -> list[dict]:
    archived = load_solved(solved_dir)
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


def load_tickets(path: Path = TICKETS_PATH) -> list[dict]:
    return normalize_tickets(json.loads(path.read_text(encoding="utf-8"))) if path.is_file() else []


def save_tickets(tickets: list[dict], path: Path = TICKETS_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(tickets, indent=2) + "\n", encoding="utf-8")


def require_ticket(ticket_id: str, path: Path = TICKETS_PATH) -> dict:
    ticket = next((item for item in load_tickets(path) if item["id"] == ticket_id), None)
    if ticket is None:
        raise SystemExit("ticket not found: {0}".format(ticket_id))
    return ticket


def set_ticket_status(ticket_id: str, status: str, run_id: str | None = None, path: Path = TICKETS_PATH) -> dict:
    tickets = load_tickets(path)
    ticket = next((item for item in tickets if item["id"] == ticket_id), None)
    if ticket is None:
        raise RuntimeError("ticket not found: {0}".format(ticket_id))
    ticket["status"] = normalize_status(status)
    if run_id:
        ticket["solver_run_id"] = run_id
    save_tickets(tickets, path)
    return ticket


def archive_solved(path: Path = TICKETS_PATH, solved_dir: Path = SOLVED_DIR, sources=None) -> list[dict]:
    keep = []
    moved = []
    solved_dir.mkdir(parents=True, exist_ok=True)
    for ticket in load_tickets(path):
        if ticket.get("status") in SOLVED:
            (solved_dir / "{0}.json".format(_safe_name(ticket["id"]))).write_text(
                json.dumps(ticket, indent=2) + "\n", encoding="utf-8"
            )
            moved.append(ticket)
            print("{0}\tarchived".format(ticket["id"]))
        else:
            keep.append(ticket)
    save_tickets(keep, path)
    if not keep:
        if sources is None:
            sources = (EMAIL_PATH, PDF_PATH) if path.resolve() == TICKETS_PATH.resolve() else ()
        for src in sources:
            if src.is_file():
                src.replace(solved_dir / src.name)
                print("{0}\tarchived".format(src.name))
    return moved


def write_run_log(ticket_id: str, kind: str, verdict: str | None, prompt: str, result_text: str | None, run_id: str | None = None, runs_dir: Path = RUNS_DIR) -> Path:
    runs_dir.mkdir(parents=True, exist_ok=True)
    path = runs_dir / "{0}-{1}.md".format(_safe_name(ticket_id), _safe_name(run_id or kind))
    path.write_text(
        "# {0} {1}\n\n- verdict: {2}\n- run: {3}\n\n## Prompt\n{4}\n\n## Result\n{5}\n".format(
            ticket_id, kind, verdict or "none", run_id or "", prompt, result_text or ""
        ),
        encoding="utf-8",
    )
    return path


def run_step(ticket_id: str, want: str, kind: str, make_prompt, next_status: dict[str, str], fallback: str = "no verdict") -> None:
    ticket = require_ticket(ticket_id)
    if ticket["status"] != want:
        print("{0}\tskipped\t{1}".format(ticket_id, ticket["status"]))
        return
    prompt = make_prompt(ticket, code_context())
    result = run_cursor(prompt)
    if result.result:
        print(result.result)
    verdict = last_verdict(result.result)
    write_run_log(ticket_id, kind, verdict, prompt, result.result, result.id)
    status = next_status.get(verdict)
    if status:
        set_ticket_status(ticket_id, status, result.id)
        if verdict == FAILED:
            print("{0}\t{1}\t{2}".format(ticket_id, status, FAILED))
        else:
            print("{0}\t{1}".format(ticket_id, status))
        return
    print("{0}\t{1}\t{2}".format(ticket_id, want, verdict or fallback))
