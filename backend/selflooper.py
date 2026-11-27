"""Solve FleetAI from open tickets, or from one instruction. No sign-in.

An instruction is analyzed in the FleetAI checkout, saved as tickets, solved,
tested, and published by merging fleetai/dev into main. Pushing main is the deploy.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID

import connections
import db
import intakes
import orchestrator
from config import (
    COMPLETED,
    FIXED,
    UNRESOLVED,
    VERIFYING,
    active_checkout,
    ensure_code_context,
    normalize_tickets,
    product_cwd,
)

DEV_BRANCH = "fleetai/dev"
MAIN_BRANCH = "main"
SSH_REMOTE = "git@github.com:netpalm-ai/fleetai.git"

_REQUIRED = (
    "## Product",
    "## Org",
    "## Repositories",
    "## Runtime flow",
    "fleetai/frontend",
    "fleetai/dev",
)

_BREAKDOWN = """Read the FleetAI checkout and this instruction. Do not edit files. Do not commit, push, or deploy.

Break the instruction into the smallest set of engineering tickets that cover it. Read the pages and modules it names before you write a ticket. Do not invent work the instruction did not ask for.
Do not delete a database record. Do not write SQL that removes rows, truncates a table, drops stored data, or otherwise destroys a database. Do not run a test, script, or migration against a database that already holds records.

Return a JSON array only. Each object must have:
- id: a new short slug. Do not reuse an existing id
- title
- severity
- services: names from CODE CONTEXT, else []
- context: the change, naming the files to edit
- expected: the behaviour after the change

EXISTING IDS
{existing}

PREVIOUS RUNS
{runs}

CODE CONTEXT
{context}

INSTRUCTION
{instruction}
"""


def fleetai_project() -> dict:
    with db.get_pool().connection() as conn:
        row = conn.execute(
            """
            SELECT p.id, p.user_id
            FROM projects p
            JOIN project_contexts c ON c.project_id = p.id AND c.user_id = p.user_id
            WHERE p.name = 'FleetAI' AND c.product_name = 'FleetAI'
            ORDER BY p.created_at
            LIMIT 1
            """
        ).fetchone()
    if row is None:
        raise RuntimeError("FleetAI project is missing")
    return {"id": row["id"], "user_id": row["user_id"]}


def open_ticket_ids(user_id: UUID, project_id: UUID) -> list[str]:
    return [
        ticket["id"]
        for ticket in intakes.list_visible_tickets(user_id, project_id)
        if ticket["status"] in (UNRESOLVED, VERIFYING)
    ]


def require_context(text: str) -> None:
    missing = [part for part in _REQUIRED if part not in text]
    if missing:
        raise RuntimeError("FleetAI code context is missing {0}".format(", ".join(missing)))


def existing_ids(user_id: UUID) -> list[str]:
    with db.get_pool().connection() as conn:
        rows = conn.execute(
            "SELECT public_id FROM tickets WHERE user_id = %s ORDER BY public_id",
            (user_id,),
        ).fetchall()
    return [str(row["public_id"]) for row in rows]


def tickets_from_text(text: str) -> list[dict]:
    body = (text or "").strip()
    if body.startswith("```"):
        body = body.split("\n", 1)[1].removesuffix("```").strip()
    start = body.find("[")
    end = body.rfind("]")
    if start < 0 or end < start:
        raise RuntimeError("ticket breakdown was not a JSON array")
    tickets = normalize_tickets(json.loads(body[start : end + 1]))
    for ticket in tickets:
        ticket["status"] = UNRESOLVED
        ticket["kind"] = "new"
    return tickets


def save_tickets(user_id: UUID, project_id: UUID, tickets: list[dict]) -> None:
    with db.get_pool().connection() as conn:
        for item in tickets:
            found = conn.execute(
                "SELECT 1 FROM tickets WHERE user_id = %s AND public_id = %s",
                (user_id, item["id"]),
            ).fetchone()
            if found:
                raise RuntimeError("ticket id already exists: {0}".format(item["id"]))
            conn.execute(
                """
                INSERT INTO tickets (
                  public_id, user_id, project_id, title, severity, services, context, expected, kind, status
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'new', 'unresolved')
                """,
                (
                    item["id"],
                    user_id,
                    project_id,
                    str(item.get("title") or ""),
                    str(item.get("severity") or ""),
                    list(item.get("services") or []),
                    str(item.get("context") or ""),
                    str(item.get("expected") or ""),
                ),
            )
        conn.commit()


def close_fixed(user_id: UUID, ticket_ids: list[str]) -> None:
    for ticket_id in ticket_ids:
        ticket = intakes.find_ticket(user_id, ticket_id)
        if ticket is None:
            continue
        if ticket["status"] == FIXED:
            intakes.set_ticket_status(user_id, ticket_id, COMPLETED)
            print("closed {0}".format(ticket_id), flush=True)
        else:
            print("left {0} {1}".format(ticket_id, ticket["status"]), flush=True)


def _git(cwd: Path, token: str | None, *args: str) -> str:
    return connections.github.git(cwd, token, *args)


def _status(clone: Path) -> str:
    return _git(clone, None, "status", "--porcelain")


def changed_paths(clone: Path) -> list[str]:
    paths: list[str] = []
    for line in _status(clone).splitlines():
        entry = line[3:].strip() if len(line) > 3 else ""
        path = entry.split(" -> ")[-1].strip()
        if path:
            paths.append(path)
    return paths


def _disposable_database(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host in {"127.0.0.1", "localhost"}


def test_commands(paths: list[str], database_url: str) -> list[tuple[str, list[str]]]:
    commands: list[tuple[str, list[str]]] = []
    if any(path.startswith("frontend/") for path in paths):
        commands.append(("frontend", ["npm", "ci"]))
        commands.append(("frontend", ["npm", "run", "build"]))
    backend = [path for path in paths if path.startswith("backend/")]
    if backend and not _disposable_database(database_url):
        raise RuntimeError("tests need a disposable database")
    if any(not path.startswith("backend/auth/") for path in backend):
        commands.append(
            (
                "backend",
                [sys.executable, "-m", "pytest", "tests/test_workflow.py", "tests/test_api.py", "-q"],
            )
        )
    if any(path.startswith("backend/auth/") for path in backend):
        commands.append(("backend", [sys.executable, "-m", "pytest", "tests/test_auth.py", "-q"]))
    return commands


def run_tests(clone: Path) -> None:
    paths = changed_paths(clone)
    if not paths:
        raise RuntimeError("no changes to test")
    commands = test_commands(paths, os.getenv("DATABASE_URL") or "")
    if not commands:
        raise RuntimeError("no test command for {0}".format(", ".join(paths)))
    for relative, command in commands:
        print("testing {0}".format(" ".join(command)), flush=True)
        result = subprocess.run(command, cwd=clone / relative)
        if result.returncode != 0:
            raise RuntimeError("tests failed: {0}".format(" ".join(command)))


def _push(clone: Path, token: str | None, ref: str) -> None:
    try:
        _git(clone, token, "push", "origin", ref)
    except RuntimeError as exc:
        detail = str(exc).lower()
        rejected = "authentication" in detail or "could not read username" in detail or "invalid username" in detail
        if not rejected:
            raise
        _git(clone, None, "push", SSH_REMOTE, ref)


def _commit_message(instruction: str) -> str:
    line = " ".join(instruction.split())
    if len(line) > 72:
        line = line[:69].rstrip() + "..."
    return "fleetai: {0}".format(line or "instruction")


def publish(clone: Path, instruction: str) -> None:
    checkout = active_checkout()
    token = checkout.token if checkout else None
    branch = _git(clone, None, "rev-parse", "--abbrev-ref", "HEAD").strip()
    if branch != DEV_BRANCH:
        raise RuntimeError("checkout is {0}; required branch is {1}".format(branch, DEV_BRANCH))
    if _status(clone).strip():
        _git(clone, token, "add", "-A")
        _git(clone, token, "commit", "-m", _commit_message(instruction))
    print("pushing {0}".format(DEV_BRANCH), flush=True)
    _push(clone, token, "HEAD:{0}".format(DEV_BRANCH))
    _git(clone, token, "fetch", "origin", MAIN_BRANCH)
    _git(clone, token, "checkout", "-B", MAIN_BRANCH, "origin/{0}".format(MAIN_BRANCH))
    try:
        print("merging {0} into {1}".format(DEV_BRANCH, MAIN_BRANCH), flush=True)
        _git(clone, token, "merge", "--no-edit", DEV_BRANCH)
        print("pushing {0}".format(MAIN_BRANCH), flush=True)
        _push(clone, token, "HEAD:{0}".format(MAIN_BRANCH))
    except RuntimeError:
        try:
            _git(clone, token, "merge", "--abort")
        except RuntimeError:
            pass
        raise
    finally:
        _git(clone, token, "checkout", DEV_BRANCH)


def _user_count() -> int:
    with db.get_pool().connection() as conn:
        return int(conn.execute("SELECT count(*) AS n FROM users").fetchone()["n"])


def _probe_health() -> str:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=3) as response:
            if response.status == 200:
                return "ok"
    except Exception:
        return "down"
    return "down"


def _clip(text: str, limit: int) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[:limit]


def run_memory(project_id: UUID) -> str:
    with db.get_pool().connection() as conn:
        rows = conn.execute(
            """
            SELECT outcome, commit_sha, users_before, users_after, health
            FROM instruction_runs
            WHERE project_id = %s
            ORDER BY created_at DESC
            LIMIT 5
            """,
            (project_id,),
        ).fetchall()
    if not rows:
        return "(none)"
    lines = []
    for row in rows:
        lines.append(
            "{0} {1} users {2}->{3} health {4}".format(
                row["outcome"],
                row["commit_sha"] or "-",
                "-" if row["users_before"] is None else row["users_before"],
                "-" if row["users_after"] is None else row["users_after"],
                row["health"] or "-",
            )
        )
    return "\n".join(lines)


def begin_push_run(project_id: UUID, instruction: str, clone: Path) -> None:
    described = ", ".join(
        " ".join(command) for _relative, command in test_commands(changed_paths(clone), os.getenv("DATABASE_URL") or "")
    )
    with db.get_pool().connection() as conn:
        conn.execute(
            """
            INSERT INTO instruction_runs (
              project_id, instruction, commit_sha, test_command, users_before, outcome
            )
            VALUES (%s, %s, %s, %s, %s, 'pushing')
            """,
            (
                project_id,
                _clip(instruction, 4000),
                _clip(_git(clone, None, "rev-parse", "HEAD"), 64),
                _clip(described, 2000),
                _user_count(),
            ),
        )
        conn.commit()


def fail_pushing_run(project_id: UUID) -> None:
    with db.get_pool().connection() as conn:
        conn.execute(
            """
            UPDATE instruction_runs
            SET outcome = 'failed', health = 'down'
            WHERE project_id = %s AND outcome = 'pushing'
            """,
            (project_id,),
        )
        conn.commit()


def finish_pushing_runs(health: str) -> None:
    with db.get_pool().connection() as conn:
        rows = conn.execute(
            """
            SELECT id, users_before
            FROM instruction_runs
            WHERE outcome = 'pushing'
            ORDER BY created_at
            """
        ).fetchall()
        if not rows:
            return
        after = int(conn.execute("SELECT count(*) AS n FROM users").fetchone()["n"])
        for row in rows:
            before = row["users_before"]
            ok = health == "ok" and (before is None or after >= int(before))
            conn.execute(
                """
                UPDATE instruction_runs
                SET users_after = %s, health = %s, outcome = %s
                WHERE id = %s AND outcome = 'pushing'
                """,
                (after, _clip(health, 40), "published" if ok else "failed", row["id"]),
            )
        conn.commit()


def refuse_failed_run(project_id: UUID, health: str | None = None) -> None:
    with db.get_pool().connection() as conn:
        row = conn.execute(
            """
            SELECT id, outcome, users_before
            FROM instruction_runs
            WHERE project_id = %s
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (project_id,),
        ).fetchone()
    if row is None or row["outcome"] != "failed":
        return
    observed = _probe_health() if health is None else health
    after = _user_count()
    before = row["users_before"]
    if observed == "ok" and (before is None or after >= int(before)):
        with db.get_pool().connection() as conn:
            conn.execute(
                """
                UPDATE instruction_runs
                SET users_after = %s, health = %s, outcome = 'published'
                WHERE id = %s AND outcome = 'failed'
                """,
                (after, observed, row["id"]),
            )
            conn.commit()
        return
    raise RuntimeError(
        "last instruction failed. Refusing a new one until the live service is healthy and the user count has not fallen."
    )


def breakdown_prompt(instruction: str, context: str, used: list[str], runs: str) -> str:
    return _BREAKDOWN.format(
        existing="\n".join(used) or "(none)",
        runs=runs,
        context=context,
        instruction=instruction.strip(),
    )


def analyze(prompt: str) -> str:
    from llm import cursor

    result = cursor.run(prompt)
    return result.result or ""


def run_instruction(user_id: UUID, project_id: UUID, instruction: str) -> None:
    context = ensure_code_context(user_id, project_id)
    require_context(context)
    with connections.github.checkout_for(user_id, project_id):
        clone = product_cwd() / "fleetai"
        if not (clone / ".git").is_dir():
            raise RuntimeError("FleetAI checkout is missing")
        if _status(clone).strip():
            raise RuntimeError("FleetAI checkout is dirty")
        tickets = tickets_from_text(
            analyze(breakdown_prompt(instruction, context, existing_ids(user_id), run_memory(project_id)))
        )
        if _status(clone).strip():
            raise RuntimeError("analysis edited the checkout")
        if not tickets:
            raise RuntimeError("instruction produced no tickets")
        save_tickets(user_id, project_id, tickets)
        ticket_ids = [ticket["id"] for ticket in tickets]
        print("tickets {0}".format(", ".join(ticket_ids)), flush=True)
        orchestrator.execute(user_id, None, ticket_ids)
        missing = [
            ticket_id
            for ticket_id in ticket_ids
            if (found := intakes.find_ticket(user_id, ticket_id)) is None or found["status"] != FIXED
        ]
        if missing:
            raise RuntimeError("not fixed: {0}".format(", ".join(missing)))
        run_tests(clone)
        begin_push_run(project_id, instruction, clone)
        try:
            publish(clone, instruction)
        except RuntimeError:
            fail_pushing_run(project_id)
            raise
        finish_pushing_runs(_probe_health())
    close_fixed(user_id, ticket_ids)


def resolve_open(user_id: UUID, project_id: UUID) -> None:
    require_context(ensure_code_context(user_id, project_id))
    ticket_ids = open_ticket_ids(user_id, project_id)
    with connections.github.checkout_for(user_id, project_id):
        if not (product_cwd() / "fleetai" / ".git").is_dir():
            raise RuntimeError("FleetAI checkout is missing")
        if not ticket_ids:
            print("no open tickets", flush=True)
            return
        print("resolving {0}".format(", ".join(ticket_ids)), flush=True)
        orchestrator.execute(user_id, None, ticket_ids)
    close_fixed(user_id, ticket_ids)


def main(instruction: str = "") -> None:
    db.open_pool()
    finish_pushing_runs(_probe_health())
    project = fleetai_project()
    user_id = project["user_id"]
    project_id = project["id"]
    text = instruction.strip()
    if text:
        print("instruction {0}".format(text), flush=True)
        refuse_failed_run(project_id)
        run_instruction(user_id, project_id, text)
        return
    resolve_open(user_id, project_id)


if __name__ == "__main__":
    main(" ".join(sys.argv[1:]))
