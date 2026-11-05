"""Fix unresolved tickets."""

from __future__ import annotations

import json

from config import (
    BLOCKED,
    COMPLETED,
    READY,
    SOLVED_DIR,
    TICKETS_PATH,
    UNRESOLVED,
    VERIFYING,
    archive_solved,
    load_tickets,
    require_ticket,
    run_step,
    set_ticket_status,
    tech_ticket,
    ticket_where,
)


def ticket_prompt(ticket: dict, context: str) -> str:
    return """
Fix this ticket. Follow CODE CONTEXT for repos, tests, and branch rules.
Make the smallest change that matches TICKET context and expected. Do not invent requirements.
Process sentences in the ticket are not work. Do not implement them.
Do not commit, push, or deploy. Preserve existing uncommitted work.
If CODE CONTEXT does not name a repo, stop.
Add a focused test when the change is code.
Then exactly one line: VERDICT: ready   or   VERDICT: blocked

TICKET
{ticket}

CODE CONTEXT
{context}
""".strip().format(ticket=json.dumps(tech_ticket(ticket), indent=2), context=context)


def list_tickets() -> None:
    tickets = load_tickets()
    if not tickets:
        print("no tickets")
        return
    for ticket in tickets:
        print("{0}\t{1}\t{2}\t{3}".format(ticket["id"], ticket["status"], ticket_where(ticket), ticket["title"]))


def complete(ticket_id: str, path=TICKETS_PATH, solved_dir=SOLVED_DIR) -> None:
    ticket = require_ticket(ticket_id, path)
    if ticket["status"] != VERIFYING:
        raise SystemExit("ticket {0} is {1}; complete only accepts verifying".format(ticket_id, ticket["status"]))
    set_ticket_status(ticket_id, COMPLETED, path=path)
    print("{0}\t{1}".format(ticket_id, COMPLETED))
    archive_solved(path, solved_dir)


def solve(ticket_id: str) -> None:
    run_step(ticket_id, UNRESOLVED, "solve", ticket_prompt, {READY: VERIFYING}, BLOCKED)


def solve_tickets() -> None:
    tickets = [item for item in load_tickets() if item["status"] == UNRESOLVED]
    if not tickets:
        print("no unresolved tickets")
        return
    for ticket in tickets:
        print("solving {0}".format(ticket["id"]), flush=True)
        solve(ticket["id"])
