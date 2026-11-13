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
    locked,
    require_ticket,
    run_step,
    set_ticket_status,
    tech_ticket,
    ticket_where,
)


def ticket_prompt(ticket: dict, context: str) -> str:
    return """
Fix this ticket. Follow ENGINEERING STANDARD. Follow CODE CONTEXT for this product. Do not invent requirements.
Process sentences in the ticket are not work. Do not implement them.
If CODE CONTEXT names a required branch and HEAD is not on it, stop.
If the item is not a software defect, the evidence contradicts the ticket, or the behaviour is already in the tree, do not patch.
Add a focused test when the change is code.
Before VERDICT: ready, list each named item as done, not done, or deferred. Silence is not ready. Partly done is not ready.
Then exactly one line: VERDICT: ready   or   VERDICT: blocked

TICKET
{ticket}

{context}
""".strip().format(ticket=json.dumps(tech_ticket(ticket), indent=2), context=context)


def list_tickets() -> None:
    tickets = load_tickets()
    if not tickets:
        print("no tickets")
        return
    for ticket in tickets:
        print("{0}\t{1}\t{2}\t{3}".format(ticket["id"], ticket["status"], ticket_where(ticket), ticket["title"]))


@locked
def complete(ticket_id: str, path=TICKETS_PATH, solved_dir=SOLVED_DIR) -> None:
    ticket = require_ticket(ticket_id, path)
    if ticket["status"] != VERIFYING:
        raise SystemExit("ticket {0} is {1}; complete only accepts verifying".format(ticket_id, ticket["status"]))
    set_ticket_status(ticket_id, COMPLETED, path=path)
    print("{0}\t{1}".format(ticket_id, COMPLETED))
    archive_solved(path, solved_dir)


@locked
def solve(ticket_id: str) -> None:
    run_step(ticket_id, UNRESOLVED, "solve", ticket_prompt, {READY: VERIFYING}, BLOCKED)


@locked
def solve_tickets() -> None:
    tickets = [item for item in load_tickets() if item["status"] == UNRESOLVED]
    if not tickets:
        print("no unresolved tickets")
        return
    for ticket in tickets:
        print("solving {0}".format(ticket["id"]), flush=True)
        solve(ticket["id"])
